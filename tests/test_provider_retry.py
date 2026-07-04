"""REL-05 — bounded retry with backoff for transient provider errors.

Retries connection errors, timeouts, and HTTP 429/5xx (up to 3 attempts);
never retries other 4xx. Sleeps are patched out so tests stay fast.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

import httpx

from app.core.llm_providers.http import post_with_retry


class _FakeResponse:
    def __init__(self, status_code: int, json_body: dict | None = None) -> None:
        self.status_code = status_code
        self._json = json_body or {}

    def json(self) -> dict:
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("POST", "http://x/api"),
                response=httpx.Response(self.status_code),
            )


class _ScriptedClient:
    """Async client whose .post yields a scripted sequence of responses/exceptions."""

    def __init__(self, script: list) -> None:
        self._script = list(script)
        self.calls = 0

    async def post(self, url, *, json=None, headers=None):  # noqa: A002
        self.calls += 1
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class PostWithRetryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._sleep_patch = patch(
            "app.core.llm_providers.http.asyncio.sleep", new=AsyncMock()
        )
        self.mock_sleep = self._sleep_patch.start()

    async def asyncTearDown(self) -> None:
        self._sleep_patch.stop()

    async def test_503_then_200_succeeds(self) -> None:
        client = _ScriptedClient([_FakeResponse(503), _FakeResponse(200, {"ok": True})])
        resp = await post_with_retry(client, "/api", json={})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(client.calls, 2)

    async def test_persistent_400_not_retried(self) -> None:
        client = _ScriptedClient([_FakeResponse(400), _FakeResponse(200)])
        resp = await post_with_retry(client, "/api", json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(client.calls, 1)  # returned immediately, no retry

    async def test_429_is_retried(self) -> None:
        client = _ScriptedClient([_FakeResponse(429), _FakeResponse(200)])
        resp = await post_with_retry(client, "/api", json={})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(client.calls, 2)

    async def test_connect_error_then_success(self) -> None:
        client = _ScriptedClient(
            [httpx.ConnectError("refused"), _FakeResponse(200)]
        )
        resp = await post_with_retry(client, "/api", json={})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(client.calls, 2)

    async def test_persistent_5xx_returns_last_response(self) -> None:
        client = _ScriptedClient([_FakeResponse(503)] * 3)
        resp = await post_with_retry(client, "/api", json={}, max_attempts=3)
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(client.calls, 3)  # exhausted attempts

    async def test_persistent_connect_error_raises(self) -> None:
        client = _ScriptedClient([httpx.ConnectError("refused")] * 3)
        with self.assertRaises(httpx.ConnectError):
            await post_with_retry(client, "/api", json={}, max_attempts=3)
        self.assertEqual(client.calls, 3)


class OllamaCompleteRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_complete_retries_transient_then_succeeds(self) -> None:
        from app.core.llm_providers.ollama import OllamaProvider

        client = _ScriptedClient(
            [
                _FakeResponse(503),
                _FakeResponse(200, {"message": {"content": "hi", "tool_calls": []}}),
            ]
        )
        with patch(
            "app.core.llm_providers.ollama.get_client", return_value=client
        ), patch("app.core.llm_providers.http.asyncio.sleep", new=AsyncMock()):
            result = await OllamaProvider().complete([{"role": "user", "content": "x"}])

        self.assertEqual(result.content, "hi")
        self.assertEqual(client.calls, 2)


if __name__ == "__main__":
    unittest.main()
