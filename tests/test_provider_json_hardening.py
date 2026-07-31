"""Providers must survive malformed JSON from the model, not raise.

A small model that emits a broken ``arguments`` string used to abort the whole
turn with ``JSONDecodeError``, which the compat API then reported to the coach
as "I'm temporarily unable to reach the model" — a parse bug disguised as an
outage. These tests pin the degrade-don't-raise behaviour and the honest error
hint that replaced it.
"""

from __future__ import annotations

import json
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.core.llm_providers.ollama import OllamaProvider
from app.core.llm_providers.openai_compat import OpenAIProvider
from app.core.llm_providers.openrouter import OpenRouterProvider


def _ollama_body(arguments) -> dict:
    return {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "get_client", "arguments": arguments}}],
        }
    }


def _openai_body(arguments) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {"name": "get_client", "arguments": arguments},
                        }
                    ],
                }
            }
        ]
    }


def _response(body: dict) -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value=body)
    return response


class ToolArgumentParsingTests(unittest.IsolatedAsyncioTestCase):
    async def _complete(self, module: str, provider, body: dict):
        with patch(f"{module}.get_client", MagicMock()), patch(
            f"{module}.post_with_retry", new=AsyncMock(return_value=_response(body))
        ):
            return await provider.complete([{"role": "user", "content": "hi"}])

    async def test_ollama_dict_arguments(self) -> None:
        result = await self._complete(
            "app.core.llm_providers.ollama",
            OllamaProvider(),
            _ollama_body({"client_id": 4}),
        )
        self.assertEqual(result.tool_calls[0].arguments, {"client_id": 4})

    async def test_ollama_python_literal_arguments_recovered(self) -> None:
        result = await self._complete(
            "app.core.llm_providers.ollama",
            OllamaProvider(),
            _ollama_body('{"client_id": 4, "verbose": True}'),
        )
        self.assertEqual(
            result.tool_calls[0].arguments, {"client_id": 4, "verbose": True}
        )

    async def test_ollama_malformed_arguments_degrade_to_empty(self) -> None:
        result = await self._complete(
            "app.core.llm_providers.ollama",
            OllamaProvider(),
            _ollama_body('{"client_id": 4, "note": "cut off mid'),
        )
        self.assertEqual(result.tool_calls[0].arguments, {})
        self.assertEqual(result.tool_calls[0].name, "get_client")

    async def test_openai_malformed_arguments_degrade_to_empty(self) -> None:
        result = await self._complete(
            "app.core.llm_providers.openai_compat",
            OpenAIProvider(model="local-model"),
            _openai_body("not json at all"),
        )
        self.assertEqual(result.tool_calls[0].arguments, {})

    async def test_openrouter_malformed_arguments_degrade_to_empty(self) -> None:
        result = await self._complete(
            "app.core.llm_providers.openrouter",
            OpenRouterProvider(model="openai/gpt-4o-mini"),
            _openai_body("{'client_id': 4,}"),
        )
        self.assertEqual(result.tool_calls[0].arguments, {})


class OllamaStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_unparseable_line_does_not_kill_the_stream(self) -> None:
        lines = [
            json.dumps({"message": {"content": "Let's "}}),
            "",  # keep-alive
            "{partial chunk",  # truncated frame
            json.dumps({"message": {"content": "begin."}}),
        ]

        response = MagicMock()
        response.raise_for_status = MagicMock()

        async def _aiter_lines():
            for line in lines:
                yield line

        response.aiter_lines = _aiter_lines

        @asynccontextmanager
        async def _stream(*args, **kwargs):
            yield response

        client = MagicMock()
        client.stream = _stream

        with patch("app.core.llm_providers.ollama.get_client", MagicMock(return_value=client)):
            chunks = [
                chunk
                async for chunk in OllamaProvider().stream(
                    [{"role": "user", "content": "hi"}]
                )
            ]

        self.assertEqual("".join(chunks), "Let's begin.")


class ErrorHintTests(unittest.TestCase):
    def test_invalid_json_is_not_reported_as_an_outage(self) -> None:
        from app.api.openai_compat import _llm_error_hint

        exc = json.JSONDecodeError("Expecting value", "<html>", 0)
        self.assertEqual(
            _llm_error_hint(exc, backend="ollama"), "Ollama returned invalid JSON"
        )

    def test_connect_error_hint_unchanged(self) -> None:
        from app.api.openai_compat import _llm_error_hint

        self.assertEqual(
            _llm_error_hint(httpx.ConnectError("boom"), backend="ollama"),
            "could not connect to Ollama",
        )


if __name__ == "__main__":
    unittest.main()
