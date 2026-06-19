"""LLM client — routes requests to the appropriate provider."""

import json
import logging
import re
from typing import TYPE_CHECKING, AsyncGenerator, Optional, Union

from app.core.config import settings
from app.core.observability import log_step
from app.core.prompts import COACH_ASSISTANT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.memory.store import MemoryStore

_MAX_TOOL_ITERATIONS = 5
_JSON_WRAPPER_KEYS = ("response", "answer", "content", "message")
_FOLLOW_UP_ONLY_KEYS = frozenset({"follow_ups", "followups", "follow_up_questions"})
_FOLLOW_UP_LIST_KEYS = ("follow_ups", "followups", "follow_up_questions")

# Patterns that indicate the user is asking for data, not coaching advice.
# When the LLM returns only follow-ups for these, it is a dead-end to be rescued.
_DATA_REQUEST_PATTERNS = re.compile(
    r"\b(?:"
    r"list|show|give|fetch|get|pull|display|retrieve|dump|print|output|"
    r"who\s+are|who\s+is|what\s+are|what\s+is|tell\s+me|show\s+me"
    r")\b.{0,60}\b(?:"
    r"client|clients|patient|patients|visitor|visitors|contact|contacts|"
    r"person|people|member|members|roster|database|records|table|notes?|goals?|"
    r"decisions?|progress|story|stories|details?|info|information|profile|data"
    r")\b",
    re.IGNORECASE | re.DOTALL,
)


def _last_user_message(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content", "")
            return content if isinstance(content, str) else ""
    return ""


def _sanitize_assistant_reply(content: str, *, last_user: str = "") -> str:
    """Strip JSON wrappers some models emit instead of plain text."""
    stripped = content.strip()
    if not stripped.startswith("{"):
        return content

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return content

    if not isinstance(data, dict):
        return content

    for key in _JSON_WRAPPER_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    if set(data.keys()) <= _FOLLOW_UP_ONLY_KEYS:
        return _format_follow_ups_as_text(data, last_user=last_user)

    return content


def _is_data_request(message: str) -> bool:
    """Return True when *message* looks like a data retrieval request."""
    return bool(_DATA_REQUEST_PATTERNS.search(message.strip()))


def _format_follow_ups_as_text(data: dict, *, last_user: str = "") -> str:
    """Turn follow-up-only JSON into readable coaching prompts.

    When the last user message looks like a data request (list/show/fetch
    clients, notes, etc.) the follow-ups are NOT surfaced — they represent a
    model failure to call a tool.  Return an empty string in that case so the
    caller falls through to the empty-reply rescue path.
    """
    if last_user and _is_data_request(last_user):
        # Data request → suppress follow-ups; empty triggers rescue in caller.
        return ""

    for key in _FOLLOW_UP_LIST_KEYS:
        items = data.get(key)
        if not isinstance(items, list):
            continue
        questions = [str(item).strip() for item in items if str(item).strip()]
        if questions:
            lines = "\n".join(f"- {question}" for question in questions)
            return f"Here are some angles to explore:\n\n{lines}"
    return ""


def _empty_reply_fallback(last_user: str, store: "MemoryStore") -> str:
    from app.core.client_intents import detect_client_mention, try_direct_client_action

    # Attempt one more rescue via the direct-action path before giving up.
    if last_user and _is_data_request(last_user):
        rescue = try_direct_client_action(last_user, store)
        if rescue is not None:
            return rescue
        return (
            "I couldn't retrieve that data. "
            "Could you clarify which client or record you're asking about?"
        )

    if detect_client_mention(last_user, store):
        return (
            "I wasn't able to put together a full coaching response just now. "
            "Could you rephrase your question, or ask me to pull up that client's "
            "notes so we can work from what's on file?"
        )
    return (
        "I'm not sure I understood that. "
        "Could you please provide more details or specify the client's name?"
    )


def _client_context_for_prompt(client_id: str, store: "MemoryStore") -> str:
    from app.core.tools import execute_tool

    record = execute_tool("get_client_full", {"client_id": client_id}, store)
    if record.startswith("❌"):
        return ""
    return (
        "## Referenced Client Record\n"
        "The coach is asking about this client. Use their profile and notes "
        "below to give specific, actionable coaching guidance.\n\n"
        f"{record}"
    )


def _format_direct_lookup_reply(tool_result: str) -> str:
    if tool_result.startswith("❌"):
        return tool_result
    return f"Here are the details on file:\n\n{tool_result}"


async def _try_llm_router_action(
    message: str,
    store: "MemoryStore",
    provider,
) -> Optional[str]:
    """Use the LLM router fallback to classify and execute a tool.

    Returns a formatted tool result string when confident, or ``None`` to
    fall through to the full tool-calling loop.
    """
    from app.core.client_intents import (
        detect_client_lookup,
        detect_client_mention,
        detect_create_client,
        detect_profile_update,
    )
    from app.core.llm_router import classify_tool_llm
    from app.core.tools import execute_tool

    match = await classify_tool_llm(message, provider=provider)
    if match is None:
        return None

    tool = match.tool

    if tool == "list_clients":
        result = execute_tool("list_clients", {}, store)
        return _format_direct_lookup_reply(result)

    if tool == "create_client":
        profile_args = detect_profile_update(message, store)
        if profile_args:
            return execute_tool("create_client", profile_args, store)
        create_args = detect_create_client(message)
        if create_args:
            return execute_tool("create_client", create_args, store)
        return None

    if tool in ("get_client", "get_client_full"):
        client_ref = detect_client_lookup(message)
        if client_ref:
            result = execute_tool(tool, {"client_id": client_ref}, store)
            return _format_direct_lookup_reply(result)
        client_id = detect_client_mention(message, store)
        if client_id:
            result = execute_tool(tool, {"client_id": client_id}, store)
            return _format_direct_lookup_reply(result)
        return None

    if tool == "list_client_notes":
        client_id = detect_client_mention(message, store)
        if client_id is None:
            return None
        result = execute_tool("list_client_notes", {"client_id": client_id}, store)
        return _format_direct_lookup_reply(result)

    # For write/delete tools, defer to the full LLM loop for param extraction
    # and confirmation flow.
    return None


def try_direct_reply(
    message: str,
    store: "MemoryStore",
    messages: Optional[list[dict]] = None,
) -> Optional[str]:
    """Return a final reply for deterministic client commands, else None."""
    from app.core.client_intents import (
        SIMPLE_GREETING_REPLY,
        is_simple_greeting,
        try_direct_client_action,
    )
    from app.core.scope import is_openwebui_task, scope_guard

    text = message.strip()
    if not text or is_openwebui_task(text):
        log_step(logger, "direct_reply", "skip", level=logging.DEBUG, reason="empty_or_task")
        return None

    if is_simple_greeting(text):
        log_step(logger, "direct_reply", "hit", reason="greeting")
        return SIMPLE_GREETING_REPLY

    refusal = scope_guard(text)
    if refusal is not None:
        log_step(logger, "direct_reply", "hit", reason="scope_block")
        return refusal

    direct = try_direct_client_action(text, store, messages)
    if direct is None:
        log_step(logger, "direct_reply", "miss", level=logging.DEBUG)
        return None
    outcome = "preview" if direct.startswith("⏳") else ("ok" if direct.startswith("✅") else "hit")
    log_step(logger, "direct_reply", outcome)
    if direct.startswith(("⏳", "✅", "❌")):
        return direct
    return _format_direct_lookup_reply(direct)


async def generate_response(
    messages: list[dict[str, str]],
    system_prompt: str = COACH_ASSISTANT_SYSTEM_PROMPT,
    stream: bool = False,
    tools: Optional[list[dict]] = None,
    store: Optional["MemoryStore"] = None,
    model_id: Optional[str] = None,
) -> Union[str, AsyncGenerator[str, None]]:
    """Send messages to the resolved provider and return the assistant response.

    Args:
        messages: List of {"role": ..., "content": ...} message dicts.
        system_prompt: System prompt to prepend.
        stream: Whether to stream the response.
        tools: Optional list of tool definitions for function calling.
        store: MemoryStore instance required when tools are provided.
        model_id: Virtual model ID (e.g. "coach-assistant-ai-cloud").
                  Defaults to local Ollama when None or unrecognised.

    Returns:
        The assistant's reply as a string (non-streaming) or an async generator
        (streaming). When tools are provided, always returns a string and ``stream``
        is ignored.

    Raises:
        ValueError: If ``tools`` is provided without a ``store``.
    """
    from app.core.model_registry import resolve_provider

    provider = resolve_provider(model_id)

    if tools:
        if store is None:
            raise ValueError("store is required when tools are provided")
        return await _generate_with_tools(messages, system_prompt, tools, store, provider)

    full_messages = [{"role": "system", "content": system_prompt}] + list(messages)

    if stream:
        return provider.stream(full_messages, temperature=settings.temperature_advice)

    result = await provider.complete(full_messages, temperature=settings.temperature_advice)
    return result.content


async def _generate_with_tools(
    messages: list[dict],
    system_prompt: str,
    tools: list[dict],
    store: "MemoryStore",
    provider=None,
) -> str:
    """Agentic tool-calling loop: execute tools until the LLM gives a final reply."""
    from app.core.llm_providers.ollama import OllamaProvider

    if provider is None:
        provider = OllamaProvider()

    from app.core.client_intents import (
        NOTE_WRITE_MISFIRE_GUIDANCE,
        detect_client_mention,
        is_coaching_advice_request,
        looks_like_malformed_tool_call,
        parse_text_tool_call,
        profile_update_from_add_note,
        try_direct_client_action,
    )
    from app.core.llm_providers.types import ToolCall
    from app.core.scope import is_openwebui_task, scope_guard
    from app.core.tools import execute_tool, sanitize_write_confirmation

    last_user = _last_user_message(messages)
    # Open WebUI task prompts (follow-up suggestions, title, tags) are passed
    # straight to the model: no deterministic intent shortcuts, no scope guard,
    # and the raw JSON reply is returned unsanitized so the UI can parse it.
    is_task = bool(last_user) and is_openwebui_task(last_user)

    if last_user and not is_task:
        direct = try_direct_reply(last_user, store, messages)
        if direct is not None:
            from app.core.response_formatter import format_data_reply, is_formattable
            if is_formattable(direct):
                direct = await format_data_reply(last_user, direct, provider)
            return direct

        # LLM router fallback: one constrained call to pick a tool name when all
        # deterministic layers deferred.  Only fired for data retrieval messages
        # (_is_data_request); write operations go straight to the tool loop so
        # their confirmation flow is preserved and no extra call is made.
        if _is_data_request(last_user):
            llm_router_result = await _try_llm_router_action(
                last_user, store, provider
            )
            if llm_router_result is not None:
                from app.core.response_formatter import format_data_reply, is_formattable
                if is_formattable(llm_router_result):
                    llm_router_result = await format_data_reply(
                        last_user, llm_router_result, provider
                    )
                return llm_router_result

        client_id = detect_client_mention(last_user, store)
        if client_id:
            client_context = _client_context_for_prompt(client_id, store)
            if client_context:
                system_prompt = f"{system_prompt}\n\n{client_context}"

    full_messages = [{"role": "system", "content": system_prompt}] + list(messages)

    for iteration in range(_MAX_TOOL_ITERATIONS):
        log_step(logger, "llm.iteration", "start", level=logging.DEBUG,
                 n=iteration + 1, max=_MAX_TOOL_ITERATIONS)
        result = await provider.complete(
            full_messages,
            tools=tools,
            temperature=settings.temperature_tool,
        )

        if not result.has_tool_calls:
            raw_content = result.content
            if is_task:
                log_step(logger, "llm", "final", reason="task_complete",
                         iteration=iteration + 1)
                return raw_content

            text_tool = parse_text_tool_call(raw_content)
            if text_tool:
                tool_name, params = text_tool
                log_step(logger, "llm.tool_call", "text_parsed",
                         level=logging.DEBUG, tool=tool_name,
                         iteration=iteration + 1)
                tc = ToolCall(id=f"call_text_{tool_name}", name=tool_name, arguments=params)
                if tool_name == "add_client_note" and is_coaching_advice_request(last_user):
                    log_step(logger, "llm.tool_call", "blocked",
                             tool=tool_name, reason="coaching_advice_misfire",
                             iteration=iteration + 1)
                    full_messages.append(result.assistant_message)
                    full_messages.append(
                        provider.tool_result_message(tc, NOTE_WRITE_MISFIRE_GUIDANCE)
                    )
                    continue
                if tool_name == "add_client_note":
                    profile_args = profile_update_from_add_note(params, store)
                    if profile_args is not None:
                        log_step(logger, "llm.tool_call", "redirected",
                                 level=logging.DEBUG,
                                 from_tool=tool_name, to_tool="create_client")
                        tool_name = "create_client"
                        params = profile_args
                params = sanitize_write_confirmation(tool_name, params, last_user)
                tool_result = execute_tool(tool_name, params, store)
                full_messages.append(result.assistant_message)
                full_messages.append(provider.tool_result_message(tc, tool_result))
                if tool_result.startswith(("⏳", "✅", "❌")):
                    log_step(logger, "llm", "final", reason="write_outcome",
                             iteration=iteration + 1)
                    return tool_result
                continue

            if looks_like_malformed_tool_call(raw_content):
                log_step(logger, "llm", "fallback", level=logging.WARNING,
                         reason="malformed_tool_call", iteration=iteration + 1)
                plain_messages = [{"role": "system", "content": system_prompt}] + list(messages)
                plain_result = await provider.complete(
                    plain_messages, temperature=settings.temperature_tool
                )
                content = _sanitize_assistant_reply(plain_result.content, last_user=last_user)
                if content.strip() and not looks_like_malformed_tool_call(content):
                    log_step(logger, "llm", "final", reason="malformed_retry_ok",
                             iteration=iteration + 1)
                    return content

            content = _sanitize_assistant_reply(raw_content, last_user=last_user)
            if not content.strip() and last_user:
                log_step(logger, "llm", "fallback", level=logging.WARNING,
                         reason="empty_reply", iteration=iteration + 1)
                fallback = try_direct_client_action(last_user, store, messages)
                if fallback is not None:
                    if fallback.startswith(("⏳", "✅", "❌")):
                        return fallback
                    return _format_direct_lookup_reply(fallback)
                return _empty_reply_fallback(last_user, store)
            log_step(logger, "llm", "final", reason="content",
                     iteration=iteration + 1)
            return content

        full_messages.append(result.assistant_message)

        for tc in result.tool_calls:
            if tc.name == "add_client_note" and is_coaching_advice_request(last_user):
                log_step(logger, "llm.tool_call", "blocked",
                         tool=tc.name, reason="coaching_advice_misfire",
                         iteration=iteration + 1)
                full_messages.append(
                    provider.tool_result_message(tc, NOTE_WRITE_MISFIRE_GUIDANCE)
                )
                continue
            tool_name = tc.name
            arguments = tc.arguments
            if tool_name == "add_client_note":
                profile_args = profile_update_from_add_note(arguments, store)
                if profile_args is not None:
                    log_step(logger, "llm.tool_call", "redirected",
                             level=logging.DEBUG,
                             from_tool=tool_name, to_tool="create_client")
                    tool_name = "create_client"
                    arguments = profile_args
            log_step(logger, "llm.tool_call", "executing",
                     tool=tool_name, iteration=iteration + 1)
            arguments = sanitize_write_confirmation(tool_name, arguments, last_user)
            tool_result = execute_tool(tool_name, arguments, store)
            full_messages.append(provider.tool_result_message(tc, tool_result))
            # Stop after write previews, outcomes, and errors so the coach
            # must reply yes/confirm before anything is saved or deleted.
            if tool_result.startswith(("⏳", "✅", "❌")):
                log_step(logger, "llm", "final", reason="write_outcome",
                         iteration=iteration + 1)
                return tool_result

    log_step(logger, "llm", "fail", level=logging.WARNING,
             reason="max_iterations_reached", max=_MAX_TOOL_ITERATIONS)
    return "I was unable to complete the action within the allowed steps."
