"""Tests for OpenRouter provider integration and model registry."""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.api.chat import reset_runtime_state
from main import app

DEFAULT_OPENROUTER_MODELS = (
    "openai/gpt-4o-mini,openai/gpt-oss-120b:free,"
    "openai/gpt-oss-20b:free"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _local_model_entry():
    return {
        "id": "coach-assistant-ai",
        "object": "model",
        "owned_by": "coach-assistant-ai",
        "name": "Coach Assistant AI (Local · llama3.1:8b)",
    }


def _cloud_model_entries():
    return [
        {
            "id": "coach-assistant-ai-cloud",
            "object": "model",
            "owned_by": "openrouter",
            "name": "Coach Assistant AI (Cloud · openai/gpt-4o-mini)",
        },
        {
            "id": "coach-assistant-ai-cloud-gpt-oss-120b",
            "object": "model",
            "owned_by": "openrouter",
            "name": "Coach Assistant AI (Cloud · openai/gpt-oss-120b:free)",
        },
        {
            "id": "coach-assistant-ai-cloud-gpt-oss-20b",
            "object": "model",
            "owned_by": "openrouter",
            "name": "Coach Assistant AI (Cloud · openai/gpt-oss-20b:free)",
        },
    ]


# ---------------------------------------------------------------------------
# /v1/models — dynamic model listing
# ---------------------------------------------------------------------------

class ModelListTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime_state()
        self.client = TestClient(app)

    def test_list_models_no_api_key_returns_only_local(self) -> None:
        """Without an API key the cloud model must not appear."""
        with patch("app.core.model_registry.settings") as mock_settings:
            mock_settings.openrouter_api_key = ""
            mock_settings.ollama_model = "llama3.1:8b"
            mock_settings.openrouter_models = DEFAULT_OPENROUTER_MODELS
            response = self.client.get("/v1/models")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        ids = [m["id"] for m in body["data"]]
        self.assertIn("coach-assistant-ai", ids)
        self.assertNotIn("coach-assistant-ai-cloud", ids)

    def test_list_models_with_valid_key_and_probe_returns_both(self) -> None:
        """With a working API key all cloud models must be listed."""
        with patch(
            "app.core.model_registry.probe_openrouter",
            new=AsyncMock(return_value=True),
        ), patch("app.core.model_registry.settings") as mock_settings:
            mock_settings.openrouter_api_key = "sk-or-test"
            mock_settings.ollama_model = "llama3.1:8b"
            mock_settings.openrouter_models = DEFAULT_OPENROUTER_MODELS
            response = self.client.get("/v1/models")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        ids = [m["id"] for m in body["data"]]
        self.assertIn("coach-assistant-ai", ids)
        for entry in _cloud_model_entries():
            self.assertIn(entry["id"], ids)

    def test_list_models_probe_fails_returns_only_local(self) -> None:
        """When the probe fails the cloud model must be hidden."""
        with patch(
            "app.core.model_registry.probe_openrouter",
            new=AsyncMock(return_value=False),
        ), patch("app.core.model_registry.settings") as mock_settings:
            mock_settings.openrouter_api_key = "sk-or-bad"
            mock_settings.ollama_model = "llama3.1:8b"
            mock_settings.openrouter_models = DEFAULT_OPENROUTER_MODELS
            response = self.client.get("/v1/models")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        ids = [m["id"] for m in body["data"]]
        self.assertIn("coach-assistant-ai", ids)
        self.assertNotIn("coach-assistant-ai-cloud", ids)


# ---------------------------------------------------------------------------
# /v1/chat/completions — cloud model routing
# ---------------------------------------------------------------------------

class CloudModelRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime_state()
        self.client = TestClient(app)

    def test_cloud_model_request_routes_to_openrouter_provider(self) -> None:
        """Requesting a cloud model should call generate_response with that model_id."""
        with patch(
            "app.api.openai_compat.probe_openrouter",
            new=AsyncMock(return_value=True),
        ), patch(
            "app.api.openai_compat.generate_response",
            new=AsyncMock(return_value="Cloud coaching reply."),
        ) as mock_gen:
            response = self.client.post(
                "/v1/chat/completions",
                json={
                    "model": "coach-assistant-ai-cloud-gpt-oss-120b",
                    "messages": [{"role": "user", "content": "What is my goal?"}],
                    "user": "test-user",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["model"], "coach-assistant-ai-cloud-gpt-oss-120b")
        self.assertEqual(body["choices"][0]["message"]["content"], "Cloud coaching reply.")
        call_kwargs = mock_gen.call_args.kwargs
        self.assertEqual(
            call_kwargs.get("model_id"), "coach-assistant-ai-cloud-gpt-oss-120b"
        )

    def test_cloud_model_unavailable_returns_503(self) -> None:
        """Requesting the cloud model when probe fails must return HTTP 503."""
        with patch(
            "app.api.openai_compat.probe_openrouter",
            new=AsyncMock(return_value=False),
        ):
            response = self.client.post(
                "/v1/chat/completions",
                json={
                    "model": "coach-assistant-ai-cloud",
                    "messages": [{"role": "user", "content": "Help me."}],
                },
            )

        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertIn("cloud_model_unavailable", body["error"]["code"])

    def test_unknown_model_falls_back_to_local(self) -> None:
        """An unrecognised model ID must silently fall back to the local model."""
        with patch(
            "app.api.openai_compat.generate_response",
            new=AsyncMock(return_value="Local fallback reply."),
        ) as mock_gen, patch(
            "app.api.openai_compat.try_direct_reply_with_meta",
            return_value=None,
        ):
            response = self.client.post(
                "/v1/chat/completions",
                json={
                    "model": "some-random-model",
                    "messages": [{"role": "user", "content": "Hi"}],
                    "user": "test-user",
                },
            )

        self.assertEqual(response.status_code, 200)
        call_kwargs = mock_gen.call_args.kwargs
        self.assertEqual(call_kwargs.get("model_id"), "coach-assistant-ai")


# ---------------------------------------------------------------------------
# model_registry unit tests
# ---------------------------------------------------------------------------

class ModelRegistryUnitTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_provider_local_returns_ollama(self) -> None:
        from app.core.model_registry import resolve_provider
        from app.core.llm_providers.ollama import OllamaProvider

        provider = resolve_provider("coach-assistant-ai")
        self.assertIsInstance(provider, OllamaProvider)

    async def test_resolve_provider_none_returns_ollama(self) -> None:
        from app.core.model_registry import resolve_provider
        from app.core.llm_providers.ollama import OllamaProvider

        provider = resolve_provider(None)
        self.assertIsInstance(provider, OllamaProvider)

    async def test_resolve_provider_cloud_with_key_returns_openrouter(self) -> None:
        from app.core.model_registry import resolve_provider
        from app.core.llm_providers.openrouter import OpenRouterProvider

        with patch("app.core.model_registry.settings") as mock_settings:
            mock_settings.openrouter_api_key = "sk-or-test"
            mock_settings.openrouter_models = DEFAULT_OPENROUTER_MODELS
            provider = resolve_provider("coach-assistant-ai-cloud-gpt-oss-20b")

        self.assertIsInstance(provider, OpenRouterProvider)
        self.assertEqual(provider._model, "openai/gpt-oss-20b:free")

    async def test_resolve_provider_cloud_without_key_returns_ollama(self) -> None:
        """Cloud model ID without an API key must fall back to local."""
        from app.core.model_registry import resolve_provider
        from app.core.llm_providers.ollama import OllamaProvider

        with patch("app.core.model_registry.settings") as mock_settings:
            mock_settings.openrouter_api_key = ""
            provider = resolve_provider("coach-assistant-ai-cloud")

        self.assertIsInstance(provider, OllamaProvider)

    async def test_probe_no_api_key_returns_false(self) -> None:
        from app.core import model_registry

        with patch.object(model_registry, "settings") as mock_settings:
            mock_settings.openrouter_api_key = ""
            result = await model_registry.probe_openrouter()

        self.assertFalse(result)

    async def test_openrouter_models_parsed_from_env(self) -> None:
        from app.core import model_registry

        with patch.object(model_registry, "settings") as mock_settings:
            mock_settings.openrouter_models = (
                "openai/gpt-4o-mini, anthropic/claude-3.5-sonnet"
            )
            registry = model_registry.openrouter_models()

        self.assertEqual(
            registry,
            {
                "coach-assistant-ai-cloud": "openai/gpt-4o-mini",
                "coach-assistant-ai-cloud-claude-3-5-sonnet": "anthropic/claude-3.5-sonnet",
            },
        )

    async def test_probe_caches_result(self) -> None:
        """The probe should not perform a second HTTP request within the TTL."""
        import time
        from app.core import model_registry

        # Prime the cache with a True result that expires far in the future
        model_registry._probe_cache = (True, time.monotonic() + 3600)
        with patch("app.core.model_registry.settings") as mock_settings:
            mock_settings.openrouter_api_key = "sk-or-test"
            with patch.object(model_registry, "_live_probe", new=AsyncMock()) as mock_live:
                result = await model_registry.probe_openrouter()

        self.assertTrue(result)
        mock_live.assert_not_called()
        # Reset cache to avoid affecting other tests
        model_registry._probe_cache = (False, 0.0)


# ---------------------------------------------------------------------------
# OpenRouter provider message format
# ---------------------------------------------------------------------------

class OpenRouterMessageFormatTests(unittest.TestCase):
    def test_tool_result_message_uses_tool_call_id(self) -> None:
        from app.core.llm_providers.openrouter import OpenRouterProvider
        from app.core.llm_providers.types import ToolCall

        provider = OpenRouterProvider()
        tc = ToolCall(id="call_abc123", name="list_clients", arguments={})
        msg = provider.tool_result_message(tc, "result text")

        self.assertEqual(msg["role"], "tool")
        self.assertEqual(msg["tool_call_id"], "call_abc123")
        self.assertEqual(msg["content"], "result text")
        self.assertNotIn("tool_name", msg)

    def test_ollama_tool_result_message_uses_tool_name(self) -> None:
        from app.core.llm_providers.ollama import OllamaProvider
        from app.core.llm_providers.types import ToolCall

        provider = OllamaProvider()
        tc = ToolCall(id="call_0", name="list_clients", arguments={})
        msg = provider.tool_result_message(tc, "result text")

        self.assertEqual(msg["role"], "tool")
        self.assertEqual(msg["tool_name"], "list_clients")
        self.assertEqual(msg["content"], "result text")
        self.assertNotIn("tool_call_id", msg)


# ---------------------------------------------------------------------------
# LLM failure messages — provider-aware
# ---------------------------------------------------------------------------

class LLMUnavailableMessageTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime_state()
        self.client = TestClient(app)

    @staticmethod
    def _streamed_content(response_text: str) -> str:
        tokens = []
        for line in response_text.splitlines():
            if not line.startswith("data:") or "[DONE]" in line:
                continue
            chunk = json.loads(line[len("data: "):].strip())
            for choice in chunk.get("choices", []):
                token = choice.get("delta", {}).get("content")
                if token:
                    tokens.append(token)
        return "".join(tokens)

    def test_streaming_cloud_failure_returns_openrouter_message(self) -> None:
        import httpx

        with patch(
            "app.api.openai_compat.probe_openrouter",
            new=AsyncMock(return_value=True),
        ), patch(
            "app.api.openai_compat.generate_response",
            new=AsyncMock(side_effect=httpx.TimeoutException("timed out")),
        ):
            response = self.client.post(
                "/v1/chat/completions",
                json={
                    "model": "coach-assistant-ai-cloud-gpt-oss-120b",
                    "messages": [{"role": "user", "content": "Help me coach a client."}],
                    "stream": True,
                    "user": "test-user",
                },
            )

        self.assertEqual(response.status_code, 200)
        content = self._streamed_content(response.text)
        self.assertIn("OpenRouter", content)
        self.assertNotIn("Ollama", content)
        self.assertIn("timed out", content)

    def test_streaming_local_failure_returns_ollama_message(self) -> None:
        import httpx

        with patch(
            "app.api.openai_compat.generate_response",
            new=AsyncMock(side_effect=httpx.ConnectError("connection refused")),
        ):
            response = self.client.post(
                "/v1/chat/completions",
                json={
                    "model": "coach-assistant-ai",
                    "messages": [{"role": "user", "content": "Help me coach a client."}],
                    "stream": True,
                    "user": "test-user",
                },
            )

        self.assertEqual(response.status_code, 200)
        content = self._streamed_content(response.text)
        self.assertIn("Ollama", content)
        self.assertNotIn("OpenRouter", content)

    def test_non_streaming_cloud_failure_returns_openrouter_message(self) -> None:
        import httpx

        with patch(
            "app.api.openai_compat.probe_openrouter",
            new=AsyncMock(return_value=True),
        ), patch(
            "app.api.openai_compat.generate_response",
            new=AsyncMock(side_effect=httpx.HTTPStatusError(
                "rate limited",
                request=MagicMock(),
                response=MagicMock(status_code=429),
            )),
        ):
            response = self.client.post(
                "/v1/chat/completions",
                json={
                    "model": "coach-assistant-ai-cloud-gpt-oss-120b",
                    "messages": [{"role": "user", "content": "Help me coach a client."}],
                    "stream": False,
                    "user": "test-user",
                },
            )

        self.assertEqual(response.status_code, 200)
        content = response.json()["choices"][0]["message"]["content"]
        self.assertIn("OpenRouter", content)
        self.assertNotIn("Ollama", content)
        self.assertIn("HTTP 429", content)


if __name__ == "__main__":
    unittest.main()
