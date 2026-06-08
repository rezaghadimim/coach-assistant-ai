"""OpenRouter LLM provider (optional cloud backend)."""

from __future__ import annotations

import json
import uuid
from typing import AsyncGenerator, Optional

import httpx

from app.core.config import settings
from app.core.llm_providers.types import CompletionResult, ToolCall


class OpenRouterProvider:
    """Client for OpenRouter's OpenAI-compatible /chat/completions endpoint."""

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
        }
        if settings.openrouter_http_referer:
            headers["HTTP-Referer"] = settings.openrouter_http_referer
        if settings.openrouter_app_name:
            headers["X-Title"] = settings.openrouter_app_name
        return headers

    def _build_payload(
        self,
        messages: list[dict],
        *,
        stream: bool = False,
        tools: Optional[list[dict]] = None,
    ) -> dict:
        payload: dict = {
            "model": settings.openrouter_model,
            "messages": messages,
            "stream": stream,
            "temperature": settings.temperature,
            "max_tokens": settings.max_tokens,
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
            base_url=settings.openrouter_base_url,
            timeout=settings.openrouter_timeout,
            headers=self._headers(),
        ) as client:
            response = await client.post("/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()

        choice = data["choices"][0]
        assistant_msg = choice["message"]

        raw_tool_calls = assistant_msg.get("tool_calls") or []
        tool_calls = []
        for tc in raw_tool_calls:
            func = tc.get("function", {})
            raw_args = func.get("arguments", "{}")
            arguments = raw_args if isinstance(raw_args, dict) else json.loads(raw_args)
            tool_calls.append(
                ToolCall(
                    id=tc.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                    name=func.get("name", ""),
                    arguments=arguments,
                )
            )

        return CompletionResult(
            content=assistant_msg.get("content") or "",
            tool_calls=tool_calls,
            assistant_message=assistant_msg,
        )

    async def stream(
        self,
        messages: list[dict],
    ) -> AsyncGenerator[str, None]:
        payload = self._build_payload(messages, stream=True)
        async with httpx.AsyncClient(
            base_url=settings.openrouter_base_url,
            timeout=settings.openrouter_timeout,
            headers=self._headers(),
        ) as client:
            async with client.stream(
                "POST", "/chat/completions", json=payload
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    raw = line[len("data: "):]
                    if raw.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw)
                        if content := (
                            chunk.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content")
                        ):
                            yield content
                    except json.JSONDecodeError:
                        continue

    def tool_result_message(self, tool_call: ToolCall, result: str) -> dict:
        """Build the tool-result message in OpenAI format."""
        return {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": result,
        }
