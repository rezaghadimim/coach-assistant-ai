"""Ollama LLM client wrapper."""

import json
from typing import AsyncGenerator

import httpx

from app.core.config import settings
from app.core.prompts import LIFE_COACH_SYSTEM_PROMPT


async def generate_response(
    messages: list[dict[str, str]],
    system_prompt: str = LIFE_COACH_SYSTEM_PROMPT,
    stream: bool = False,
) -> str | AsyncGenerator[str, None]:
    """Send messages to Ollama and return the assistant response.

    Args:
        messages: List of {"role": ..., "content": ...} message dicts.
        system_prompt: System prompt to prepend.
        stream: Whether to stream the response.

    Returns:
        The assistant's reply as a string (non-streaming).
    """
    full_messages = [{"role": "system", "content": system_prompt}] + messages

    payload = {
        "model": settings.ollama_model,
        "messages": full_messages,
        "stream": stream,
        "options": {
            "temperature": settings.temperature,
            "num_predict": settings.max_tokens,
        },
    }

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
