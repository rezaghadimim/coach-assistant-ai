"""Tests for OpenAIEmbedProvider's configurable base URL (self-hosted servers)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.core.config import settings
from app.core.embed_providers.openai import OpenAIEmbedProvider


def _mock_httpx_client(vectors: list[list[float]]):
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "data": [{"index": i, "embedding": v} for i, v in enumerate(vectors)]
    }
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.post = MagicMock(return_value=response)
    return client


class TestOpenAIEmbedProviderBaseUrl(unittest.TestCase):
    def test_default_host_requires_api_key(self) -> None:
        provider = OpenAIEmbedProvider(model="text-embedding-3-small")
        with patch.object(settings, "openai_api_key", ""), \
             patch.object(settings, "openai_base_url", "https://api.openai.com/v1"):
            with self.assertRaises(RuntimeError):
                provider.embed_query("hello")

    def test_self_hosted_url_does_not_require_api_key(self) -> None:
        provider = OpenAIEmbedProvider(model="e5-small")
        client = _mock_httpx_client([[0.1, 0.2]])
        with patch.object(settings, "openai_api_key", ""), \
             patch.object(settings, "openai_base_url", "http://second-server:8081/v1"), \
             patch("app.core.embed_providers.openai.httpx.Client", return_value=client):
            vector = provider.embed_query("hello")
        self.assertEqual(vector, [0.1, 0.2])
        called_url = client.post.call_args.args[0]
        self.assertEqual(called_url, "http://second-server:8081/v1/embeddings")
        headers = client.post.call_args.kwargs["headers"]
        self.assertNotIn("Authorization", headers)

    def test_probe_false_on_default_host_without_key(self) -> None:
        provider = OpenAIEmbedProvider(model="text-embedding-3-small")
        with patch.object(settings, "openai_api_key", ""), \
             patch.object(settings, "openai_base_url", "https://api.openai.com/v1"):
            self.assertFalse(provider.probe())

    def test_probe_attempts_call_on_self_hosted_url_without_key(self) -> None:
        provider = OpenAIEmbedProvider(model="e5-small")
        client = _mock_httpx_client([[0.1]])
        with patch.object(settings, "openai_api_key", ""), \
             patch.object(settings, "openai_base_url", "http://second-server:8081/v1"), \
             patch("app.core.embed_providers.openai.httpx.Client", return_value=client):
            self.assertTrue(provider.probe())

    def test_rag_embed_base_url_overrides_openai_base_url(self) -> None:
        """RAG_EMBED_BASE_URL wins over OPENAI_BASE_URL when both are set."""
        provider = OpenAIEmbedProvider(model="e5-small")
        client = _mock_httpx_client([[0.3]])
        with patch.object(settings, "openai_api_key", ""), \
             patch.object(settings, "openai_base_url", "https://api.openai.com/v1"), \
             patch.object(settings, "rag_embed_base_url", "http://second-server:8081/v1"), \
             patch("app.core.embed_providers.openai.httpx.Client", return_value=client):
            vector = provider.embed_query("hello")
        self.assertEqual(vector, [0.3])
        called_url = client.post.call_args.args[0]
        self.assertEqual(called_url, "http://second-server:8081/v1/embeddings")


if __name__ == "__main__":
    unittest.main()
