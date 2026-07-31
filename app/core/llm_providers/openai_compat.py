"""Generic OpenAI-compatible LLM provider (self-hosted vLLM/TGI/etc.)."""

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


class OpenAIProvider:
    """Client for a self-hosted OpenAI-compatible /chat/completions endpoint."""

    def __init__(self, model: Optional[str] = None) -> None:
        self._model = model or settings.openai_model

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if settings.openai_api_key:
            headers["Authorization"] = f"Bearer {settings.openai_api_key}"
        return headers

    def _build_payload(
        self,
        messages: list[dict],
        *,
        stream: bool = False,
        tools: Optional[list[dict]] = None,
        temperature: Optional[float] = None,
        num_predict: Optional[int] = None,
    ) -> dict:
        payload: dict = {
            "model": self._model,
            "messages": messages,
            "stream": stream,
            "temperature": temperature if temperature is not None else settings.temperature,
            "max_tokens": num_predict if num_predict is not None else settings.max_tokens,
            "frequency_penalty": settings.openai_frequency_penalty,
            "presence_penalty": settings.openai_presence_penalty,
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
        num_predict: Optional[int] = None,
        # format is Ollama-specific JSON-mode; accepted here for interface
        # compatibility. Self-hosted servers vary in their support for
        # response_format, so it is deliberately not forwarded — callers that
        # need clean JSON from this backend post-process with
        # ``tool_json.normalize_json_output``.
        format: Optional[Union[dict, str]] = None,
    ) -> CompletionResult:
        payload = self._build_payload(
            messages, stream=False, tools=tools, temperature=temperature,
            num_predict=num_predict,
        )
        t0 = time.monotonic()
        try:
            client = get_client(settings.openai_base_url, settings.openai_timeout)
            response = await post_with_retry(
                client, "/chat/completions", json=payload, headers=self._headers(),
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            ms = int((time.monotonic() - t0) * 1000)
            log_step(logger, "llm.provider", "fail", level=logging.ERROR,
                     provider="openai", model=self._model,
                     ms=ms, exc=type(exc).__name__)
            raise

        ms = int((time.monotonic() - t0) * 1000)
        choice = data["choices"][0]
        assistant_msg = choice["message"]

        raw_tool_calls = assistant_msg.get("tool_calls") or []
        log_step(logger, "llm.provider", "ok",
                 provider="openai", model=self._model,
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
                         level=logging.WARNING, provider="openai",
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
        client = get_client(settings.openai_base_url, settings.openai_timeout)
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
