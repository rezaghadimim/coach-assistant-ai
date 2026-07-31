"""OpenRouter LLM provider (optional cloud backend)."""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import AsyncGenerator, Optional, Union

from app.core.config import settings
from app.core.llm_providers.http import get_client, post_with_retry
from app.core.llm_providers.types import CompletionResult, ToolCall
from app.core.observability import log_step
from app.core.tool_json import parse_tool_arguments

logger = logging.getLogger(__name__)


class OpenRouterProvider:
    """Client for OpenRouter's OpenAI-compatible /chat/completions endpoint."""

    def __init__(self, model: Optional[str] = None) -> None:
        if model is not None:
            self._model = model
        else:
            slugs = [
                slug.strip()
                for slug in settings.openrouter_models.split(",")
                if slug.strip()
            ]
            self._model = slugs[0] if slugs else "openai/gpt-4o-mini"

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
        temperature: Optional[float] = None,
    ) -> dict:
        payload: dict = {
            "model": self._model,
            "messages": messages,
            "stream": stream,
            "temperature": temperature if temperature is not None else settings.temperature,
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
        temperature: Optional[float] = None,
        # format and num_predict are Ollama-specific; accepted here for interface compatibility.
        format: Optional[Union[dict, str]] = None,
        num_predict: Optional[int] = None,
    ) -> CompletionResult:
        payload = self._build_payload(
            messages, stream=False, tools=tools, temperature=temperature
        )
        t0 = time.monotonic()
        try:
            client = get_client(
                settings.openrouter_base_url, settings.openrouter_timeout
            )
            response = await post_with_retry(
                client,
                "/chat/completions",
                json=payload,
                headers=self._headers(),
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            ms = int((time.monotonic() - t0) * 1000)
            log_step(logger, "llm.provider", "fail", level=logging.ERROR,
                     provider="openrouter", model=self._model,
                     ms=ms, exc=type(exc).__name__)
            raise

        ms = int((time.monotonic() - t0) * 1000)
        choice = data["choices"][0]
        assistant_msg = choice["message"]

        raw_tool_calls = assistant_msg.get("tool_calls") or []
        log_step(logger, "llm.provider", "ok",
                 provider="openrouter", model=self._model,
                 ms=ms, tool_calls=len(raw_tool_calls))

        tool_calls = []
        for tc in raw_tool_calls:
            func = tc.get("function", {})
            raw_args = func.get("arguments", "{}")
            arguments = parse_tool_arguments(raw_args)
            if arguments is None:
                # Malformed argument string: run the tool with no arguments so it
                # errors usefully, rather than aborting the turn with a parse error.
                log_step(logger, "llm.provider", "bad_tool_args",
                         level=logging.WARNING, provider="openrouter",
                         model=self._model, tool=func.get("name", ""))
                arguments = {}
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
        *,
        temperature: Optional[float] = None,
    ) -> AsyncGenerator[str, None]:
        payload = self._build_payload(
            messages,
            stream=True,
            temperature=temperature if temperature is not None else settings.temperature_advice,
        )
        client = get_client(
            settings.openrouter_base_url, settings.openrouter_timeout
        )
        async with client.stream(
            "POST", "/chat/completions", json=payload, headers=self._headers()
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
