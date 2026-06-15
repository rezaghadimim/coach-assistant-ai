"""Tests for the LLM router fallback (app/core/llm_router.py).

All LLM provider calls are mocked so the tests run offline.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("TOOL_ROUTER_LLM_FALLBACK_ENABLED", "true")


def _make_provider(content: str):
    """Return a mock provider whose complete() returns *content*."""
    result = MagicMock()
    result.content = content
    provider = MagicMock()
    provider.complete = AsyncMock(return_value=result)
    return provider


class ParseToolFromResponseTests(unittest.TestCase):
    """Unit tests for the JSON parser."""

    def _parse(self, content: str):
        from app.core.llm_router import _parse_tool_from_response
        return _parse_tool_from_response(content)

    def test_valid_json_list_clients(self) -> None:
        self.assertEqual(self._parse('{"tool": "list_clients"}'), "list_clients")

    def test_valid_json_get_client_full(self) -> None:
        self.assertEqual(self._parse('{"tool": "get_client_full"}'), "get_client_full")

    def test_none_tool_returns_none(self) -> None:
        self.assertIsNone(self._parse('{"tool": "none"}'))

    def test_empty_tool_returns_none(self) -> None:
        self.assertIsNone(self._parse('{"tool": ""}'))

    def test_unknown_tool_returns_none(self) -> None:
        self.assertIsNone(self._parse('{"tool": "some_unknown_tool"}'))

    def test_invalid_json_returns_none(self) -> None:
        self.assertIsNone(self._parse("not json at all"))

    def test_json_embedded_in_text(self) -> None:
        content = 'Sure, here you go: {"tool": "list_clients"} — done.'
        self.assertEqual(self._parse(content), "list_clients")

    def test_missing_tool_key_returns_none(self) -> None:
        self.assertIsNone(self._parse('{"action": "list_clients"}'))

    def test_all_known_tools_accepted(self) -> None:
        from app.core.llm_router import _KNOWN_TOOLS
        for tool in _KNOWN_TOOLS:
            result = self._parse(f'{{"tool": "{tool}"}}')
            self.assertEqual(result, tool, f"Expected {tool} to be accepted")


class ClassifyToolLlmTests(unittest.IsolatedAsyncioTestCase):
    """Async tests for classify_tool_llm()."""

    async def test_returns_toolmatch_for_valid_tool(self) -> None:
        from app.core.llm_router import classify_tool_llm

        provider = _make_provider('{"tool": "list_clients"}')
        result = await classify_tool_llm("Give me all visitors", provider=provider)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.tool, "list_clients")
        self.assertEqual(result.backend, "llm")

    async def test_returns_none_for_tool_none(self) -> None:
        from app.core.llm_router import classify_tool_llm

        provider = _make_provider('{"tool": "none"}')
        result = await classify_tool_llm("How should I help my client?", provider=provider)

        self.assertIsNone(result)

    async def test_returns_none_for_unknown_tool(self) -> None:
        from app.core.llm_router import classify_tool_llm

        provider = _make_provider('{"tool": "something_unknown"}')
        result = await classify_tool_llm("Do something", provider=provider)

        self.assertIsNone(result)

    async def test_returns_none_on_provider_error(self) -> None:
        from app.core.llm_router import classify_tool_llm

        provider = MagicMock()
        provider.complete = AsyncMock(side_effect=RuntimeError("network error"))
        result = await classify_tool_llm("List all clients", provider=provider)

        self.assertIsNone(result)

    async def test_returns_none_on_invalid_json(self) -> None:
        from app.core.llm_router import classify_tool_llm

        provider = _make_provider("I cannot help with that.")
        result = await classify_tool_llm("Give me all clients", provider=provider)

        self.assertIsNone(result)

    async def test_disabled_returns_none(self) -> None:
        from app.core.llm_router import classify_tool_llm

        provider = _make_provider('{"tool": "list_clients"}')

        with patch("app.core.llm_router.settings") as mock_settings:
            mock_settings.tool_router_llm_fallback_enabled = False
            result = await classify_tool_llm("List clients", provider=provider)

        self.assertIsNone(result)

    async def test_toolmatch_has_llm_backend(self) -> None:
        from app.core.llm_router import classify_tool_llm

        provider = _make_provider('{"tool": "get_client_full"}')
        result = await classify_tool_llm("Show everything about Ali", provider=provider)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.backend, "llm")
        self.assertIsNone(result.rerank_score)
        self.assertEqual(result.score, 1.0)

    async def test_get_client_full_classified_correctly(self) -> None:
        from app.core.llm_router import classify_tool_llm

        provider = _make_provider('{"tool": "get_client_full"}')
        result = await classify_tool_llm("Tell me all about Sara", provider=provider)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.tool, "get_client_full")

    async def test_create_client_classified_correctly(self) -> None:
        from app.core.llm_router import classify_tool_llm

        provider = _make_provider('{"tool": "create_client"}')
        result = await classify_tool_llm("Reza is 31 years old", provider=provider)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.tool, "create_client")
