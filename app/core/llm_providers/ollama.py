"""Ollama LLM provider (local, always available)."""

from __future__ import annotations

import json
import logging
import time
from typing import AsyncGenerator, Optional, Union

from app.core.config import settings
from app.core.llm_providers.http import get_client, post_with_retry
from app.core.llm_providers.types import CompletionResult, ToolCall
from app.core.observability import log_step
from app.core.tool_json import parse_tool_arguments

logger = logging.getLogger(__name__)


class OllamaProvider:
    """Thin wrapper around Ollama's /api/chat REST endpoint."""

    def _build_payload(
        self,
        messages: list[dict],
        *,
        stream: bool = False,
        tools: Optional[list[dict]] = None,
        temperature: Optional[float] = None,
        num_predict: Optional[int] = None,
        # Ollama accepts either "json" (generic JSON mode) or a JSON schema dict.
        format: Optional[Union[dict, str]] = None,
    ) -> dict:
        payload: dict = {
            "model": settings.ollama_model,
            "messages": messages,
            "stream": stream,
            "keep_alive": settings.ollama_keep_alive,
            "options": {
                "temperature": temperature if temperature is not None else settings.temperature,
                "num_predict": num_predict if num_predict is not None else settings.max_tokens,
                "num_ctx": settings.ollama_num_ctx,
                "top_p": settings.top_p,
                "repeat_penalty": settings.repeat_penalty,
            },
        }
        if tools:
            payload["tools"] = tools
        if format is not None:
            payload["format"] = format
        return payload

    async def complete(
        self,
        messages: list[dict],
        *,
        tools: Optional[list[dict]] = None,
        temperature: Optional[float] = None,
        num_predict: Optional[int] = None,
        format: Optional[Union[dict, str]] = None,
    ) -> CompletionResult:
        payload = self._build_payload(
            messages,
            stream=False,
            tools=tools,
            temperature=temperature,
            num_predict=num_predict,
            format=format,
        )
        t0 = time.monotonic()
        try:
            client = get_client(settings.ollama_base_url, settings.ollama_timeout)
            response = await post_with_retry(client, "/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            ms = int((time.monotonic() - t0) * 1000)
            log_step(logger, "llm.provider", "fail", level=logging.ERROR,
                     provider="ollama", model=settings.ollama_model,
                     ms=ms, exc=type(exc).__name__)
            raise

        ms = int((time.monotonic() - t0) * 1000)
        assistant_msg = data["message"]
        raw_tool_calls = assistant_msg.get("tool_calls") or []
        log_step(logger, "llm.provider", "ok",
                 provider="ollama", model=settings.ollama_model,
                 ms=ms, tool_calls=len(raw_tool_calls))

        tool_calls = []
        for i, tc in enumerate(raw_tool_calls):
            func = tc.get("function", {})
            raw_args = func.get("arguments", {})
            arguments = parse_tool_arguments(raw_args)
            if arguments is None:
                # Small models emit malformed argument strings often enough that
                # raising here would abort the whole turn. Run the tool with no
                # arguments instead: it errors usefully, the loop can recover.
                log_step(logger, "llm.provider", "bad_tool_args",
                         level=logging.WARNING, provider="ollama",
                         model=settings.ollama_model, tool=func.get("name", ""))
                arguments = {}
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
        *,
        temperature: Optional[float] = None,
    ) -> AsyncGenerator[str, None]:
        payload = self._build_payload(
            messages,
            stream=True,
            temperature=temperature if temperature is not None else settings.temperature_advice,
        )
        client = get_client(settings.ollama_base_url, settings.ollama_timeout)
        async with client.stream("POST", "/api/chat", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    # Partial or keep-alive line: skip it rather than killing the
                    # stream mid-reply (matches the other providers' behaviour).
                    continue
                if content := chunk.get("message", {}).get("content"):
                    yield content

    def tool_result_message(self, tool_call: ToolCall, result: str) -> dict:
        """Build the tool-result message in Ollama's expected format."""
        return {"role": "tool", "tool_name": tool_call.name, "content": result}
