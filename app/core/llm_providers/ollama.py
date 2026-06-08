"""Ollama LLM provider (local, always available)."""

from __future__ import annotations

import json
from typing import AsyncGenerator, Optional

import httpx

from app.core.config import settings
from app.core.llm_providers.types import CompletionResult, ToolCall


class OllamaProvider:
    """Thin wrapper around Ollama's /api/chat REST endpoint."""

    def _build_payload(
        self,
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

    async def complete(
        self,
        messages: list[dict],
        *,
        tools: Optional[list[dict]] = None,
    ) -> CompletionResult:
        payload = self._build_payload(messages, stream=False, tools=tools)
        async with httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            timeout=settings.ollama_timeout,
        ) as client:
            response = await client.post("/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

        assistant_msg = data["message"]
        raw_tool_calls = assistant_msg.get("tool_calls") or []

        tool_calls = []
        for i, tc in enumerate(raw_tool_calls):
            func = tc.get("function", {})
            raw_args = func.get("arguments", {})
            arguments = raw_args if isinstance(raw_args, dict) else json.loads(raw_args)
            tool_calls.append(
                ToolCall(
                    # Ollama does not return a tool_call id; synthesise one.
                    id=f"call_{i}",
                    name=func.get("name", ""),
                    arguments=arguments,
                )
            )

        return CompletionResult(
            content=assistant_msg.get("content", ""),
            tool_calls=tool_calls,
            assistant_message=assistant_msg,
        )

    async def stream(
        self,
        messages: list[dict],
    ) -> AsyncGenerator[str, None]:
        payload = self._build_payload(messages, stream=True)
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

    def tool_result_message(self, tool_call: ToolCall, result: str) -> dict:
        """Build the tool-result message in Ollama's expected format."""
        return {"role": "tool", "tool_name": tool_call.name, "content": result}
