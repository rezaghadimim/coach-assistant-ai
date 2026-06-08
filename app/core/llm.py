"""Ollama LLM client wrapper."""

import json
from typing import TYPE_CHECKING, AsyncGenerator, Optional, Union

import httpx

from app.core.config import settings
from app.core.prompts import COACH_ASSISTANT_SYSTEM_PROMPT

if TYPE_CHECKING:
    from app.memory.store import MemoryStore

_MAX_TOOL_ITERATIONS = 5


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
    from app.core.tools import execute_tool  # avoid circular import

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
                return assistant_msg.get("content", "")

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
