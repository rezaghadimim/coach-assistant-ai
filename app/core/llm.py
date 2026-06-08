"""Ollama LLM client wrapper."""

import json
from typing import TYPE_CHECKING, AsyncGenerator, Optional, Union

import httpx

from app.core.config import settings
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


async def generate_response(
    messages: list[dict[str, str]],
    system_prompt: str = COACH_ASSISTANT_SYSTEM_PROMPT,
    stream: bool = False,
    tools: Optional[list[dict]] = None,
    store: Optional["MemoryStore"] = None,
) -> Union[str, AsyncGenerator[str, None]]:
    """Send messages to Ollama and return the assistant response.

    Args:
        messages: List of {"role": ..., "content": ...} message dicts.
        system_prompt: System prompt to prepend.
        stream: Whether to stream the response.
        tools: Optional list of tool definitions for function calling.
        store: MemoryStore instance required when tools are provided.

    Returns:
        The assistant's reply as a string (non-streaming) or an async generator
        (streaming). When tools are provided, always returns a string and ``stream``
        is ignored.

    Raises:
        ValueError: If ``tools`` is provided without a ``store``.
    """
    if tools:
        if store is None:
            raise ValueError("store is required when tools are provided")
        return await _generate_with_tools(messages, system_prompt, tools, store)

    full_messages = [{"role": "system", "content": system_prompt}] + messages
    payload = _build_payload(full_messages, stream=stream)

    if stream:
        return _stream_response(payload)

    async with httpx.AsyncClient(
        base_url=settings.ollama_base_url,
        timeout=settings.ollama_timeout,
    ) as client:
        response = await client.post("/api/chat", json=payload)
        response.raise_for_status()
        data = response.json()
        return data["message"]["content"]


async def _generate_with_tools(
    messages: list[dict],
    system_prompt: str,
    tools: list[dict],
    store: "MemoryStore",
) -> str:
    """Agentic tool-calling loop: execute tools until the LLM gives a final reply."""
    from app.core.client_intents import (
        detect_client_mention,
        parse_text_tool_call,
        try_direct_client_action,
    )
    from app.core.scope import is_openwebui_task, scope_guard
    from app.core.tools import execute_tool, sanitize_write_confirmation

    last_user = _last_user_message(messages)
    # Open WebUI task prompts (follow-up suggestions, title, tags) are passed
    # straight to the model: no deterministic intent shortcuts, no scope guard,
    # and the raw JSON reply is returned unsanitized so the UI can parse it.
    is_task = bool(last_user) and is_openwebui_task(last_user)

    if last_user and not is_task:
        refusal = scope_guard(last_user)
        if refusal is not None:
            return refusal

        direct = try_direct_client_action(last_user, store, messages)
        if direct is not None:
            if direct.startswith(("⏳", "✅", "❌")):
                return direct
            return _format_direct_lookup_reply(direct)

        client_id = detect_client_mention(last_user, store)
        if client_id:
            client_context = _client_context_for_prompt(client_id, store)
            if client_context:
                system_prompt = f"{system_prompt}\n\n{client_context}"

    full_messages = [{"role": "system", "content": system_prompt}] + list(messages)

    async with httpx.AsyncClient(
        base_url=settings.ollama_base_url,
        timeout=settings.ollama_timeout,
    ) as client:
        for _ in range(_MAX_TOOL_ITERATIONS):
            payload = _build_payload(full_messages, stream=False, tools=tools)
            response = await client.post("/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

            assistant_msg = data["message"]
            tool_calls = assistant_msg.get("tool_calls") or []

            if not tool_calls:
                raw_content = assistant_msg.get("content", "")
                if is_task:
                    return raw_content

                text_tool = parse_text_tool_call(raw_content)
                if text_tool:
                    tool_name, params = text_tool
                    result = execute_tool(tool_name, params, store)
                    full_messages.append(assistant_msg)
                    full_messages.append(
                        {"role": "tool", "tool_name": tool_name, "content": result}
                    )
                    if result.startswith(("⏳", "✅", "❌")):
                        return result
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

            full_messages.append(assistant_msg)

            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                raw_args = func.get("arguments", {})
                arguments = (
                    raw_args if isinstance(raw_args, dict) else json.loads(raw_args)
                )
                arguments = sanitize_write_confirmation(
                    tool_name, arguments, last_user
                )
                result = execute_tool(tool_name, arguments, store)
                full_messages.append(
                    {"role": "tool", "tool_name": tool_name, "content": result}
                )
                # Stop after write previews, outcomes, and errors so the coach
                # must reply yes/confirm before anything is saved or deleted.
                if result.startswith(("⏳", "✅", "❌")):
                    return result

    return "I was unable to complete the action within the allowed steps."


def _build_payload(
    messages: list[dict],
    *,
    stream: bool = False,
    tools: Optional[list[dict]] = None,
) -> dict:
    payload: dict = {
        "model": settings.ollama_model,
        "messages": messages,
        "stream": stream,
        "options": {
            "temperature": settings.temperature,
            "num_predict": settings.max_tokens,
        },
    }
    if tools:
        payload["tools"] = tools
    return payload


async def _stream_response(payload: dict) -> AsyncGenerator[str, None]:
    """Stream response tokens from Ollama."""
    async with httpx.AsyncClient(
        base_url=settings.ollama_base_url,
        timeout=settings.ollama_timeout,
    ) as client:
        async with client.stream("POST", "/api/chat", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line:
                    chunk = json.loads(line)
                    if content := chunk.get("message", {}).get("content"):
                        yield content
