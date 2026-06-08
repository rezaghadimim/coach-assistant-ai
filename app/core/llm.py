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
        return ""

    return content


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
    from app.core.client_intents import try_direct_client_query
    from app.core.scope import is_openwebui_task, scope_guard
    from app.core.tools import execute_tool  # avoid circular import

    last_user = _last_user_message(messages)
    # Open WebUI task prompts (follow-up suggestions, title, tags) are passed
    # straight to the model: no deterministic intent shortcuts, no scope guard,
    # and the raw JSON reply is returned unsanitized so the UI can parse it.
    is_task = bool(last_user) and is_openwebui_task(last_user)

    if last_user and not is_task:
        refusal = scope_guard(last_user)
        if refusal is not None:
            return refusal

        direct = try_direct_client_query(last_user, store)
        if direct is not None:
            return _format_direct_lookup_reply(direct)

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
                content = _sanitize_assistant_reply(raw_content)
                if not content.strip() and last_user:
                    fallback = try_direct_client_query(last_user, store)
                    if fallback is not None:
                        return _format_direct_lookup_reply(fallback)
                    return (
                        "I'm not sure I understood that. "
                        "Could you please provide more details or specify the client's name?"
                    )
                return content

            full_messages.append(assistant_msg)

            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                raw_args = func.get("arguments", {})
                arguments = (
                    raw_args if isinstance(raw_args, dict) else json.loads(raw_args)
                )
                result = execute_tool(tool_name, arguments, store)
                full_messages.append(
                    {"role": "tool", "tool_name": tool_name, "content": result}
                )

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
