"""LLM client — routes requests to the appropriate provider."""

import json
from typing import TYPE_CHECKING, AsyncGenerator, Optional, Union

from app.core.prompts import COACH_ASSISTANT_SYSTEM_PROMPT

if TYPE_CHECKING:
    from app.memory.store import MemoryStore

_MAX_TOOL_ITERATIONS = 5
_JSON_WRAPPER_KEYS = ("response", "answer", "content", "message")
_FOLLOW_UP_ONLY_KEYS = frozenset({"follow_ups", "followups", "follow_up_questions"})
_FOLLOW_UP_LIST_KEYS = ("follow_ups", "followups", "follow_up_questions")


def _last_user_message(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content", "")
            return content if isinstance(content, str) else ""
    return ""


def _sanitize_assistant_reply(content: str) -> str:
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
        return _format_follow_ups_as_text(data)

    return content


def _format_follow_ups_as_text(data: dict) -> str:
    """Turn follow-up-only JSON into readable coaching prompts."""
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
    from app.core.client_intents import detect_client_mention

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


def try_direct_reply(
    message: str,
    store: "MemoryStore",
    messages: Optional[list[dict]] = None,
) -> Optional[str]:
    """Return a final reply for deterministic client commands, else None."""
    from app.core.client_intents import try_direct_client_action
    from app.core.scope import is_openwebui_task, scope_guard

    text = message.strip()
    if not text or is_openwebui_task(text):
        return None

    refusal = scope_guard(text)
    if refusal is not None:
        return refusal

    direct = try_direct_client_action(text, store, messages)
    if direct is None:
        return None
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
        return provider.stream(full_messages)

    result = await provider.complete(full_messages)
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
            return direct

        client_id = detect_client_mention(last_user, store)
        if client_id:
            client_context = _client_context_for_prompt(client_id, store)
            if client_context:
                system_prompt = f"{system_prompt}\n\n{client_context}"

    full_messages = [{"role": "system", "content": system_prompt}] + list(messages)

    for _ in range(_MAX_TOOL_ITERATIONS):
        result = await provider.complete(full_messages, tools=tools)

        if not result.has_tool_calls:
            raw_content = result.content
            if is_task:
                return raw_content

            text_tool = parse_text_tool_call(raw_content)
            if text_tool:
                tool_name, params = text_tool
                tc = ToolCall(id=f"call_text_{tool_name}", name=tool_name, arguments=params)
                if tool_name == "add_client_note" and is_coaching_advice_request(last_user):
                    full_messages.append(result.assistant_message)
                    full_messages.append(
                        provider.tool_result_message(tc, NOTE_WRITE_MISFIRE_GUIDANCE)
                    )
                    continue
                if tool_name == "add_client_note":
                    profile_args = profile_update_from_add_note(params, store)
                    if profile_args is not None:
                        tool_name = "create_client"
                        params = profile_args
                tool_result = execute_tool(tool_name, params, store)
                full_messages.append(result.assistant_message)
                full_messages.append(provider.tool_result_message(tc, tool_result))
                if tool_result.startswith(("⏳", "✅", "❌")):
                    return tool_result
                continue

            content = _sanitize_assistant_reply(raw_content)
            if not content.strip() and last_user:
                fallback = try_direct_client_action(last_user, store, messages)
                if fallback is not None:
                    if fallback.startswith(("⏳", "✅", "❌")):
                        return fallback
                    return _format_direct_lookup_reply(fallback)
                return _empty_reply_fallback(last_user, store)
            return content

        full_messages.append(result.assistant_message)

        for tc in result.tool_calls:
            if tc.name == "add_client_note" and is_coaching_advice_request(last_user):
                full_messages.append(
                    provider.tool_result_message(tc, NOTE_WRITE_MISFIRE_GUIDANCE)
                )
                continue
            tool_name = tc.name
            arguments = tc.arguments
            if tool_name == "add_client_note":
                profile_args = profile_update_from_add_note(arguments, store)
                if profile_args is not None:
                    tool_name = "create_client"
                    arguments = profile_args
            arguments = sanitize_write_confirmation(tool_name, arguments, last_user)
            tool_result = execute_tool(tool_name, arguments, store)
            full_messages.append(provider.tool_result_message(tc, tool_result))
            # Stop after write previews, outcomes, and errors so the coach
            # must reply yes/confirm before anything is saved or deleted.
            if tool_result.startswith(("⏳", "✅", "❌")):
                return tool_result

    return "I was unable to complete the action within the allowed steps."
