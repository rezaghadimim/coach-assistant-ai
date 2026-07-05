"""Tests for the Ollama embedding client (mocked HTTP — no real Ollama needed)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

_OLLAMA_HTTPX = "app.core.embed_providers.ollama.httpx.Client"
_OLLAMA_SETTINGS = "app.core.config.settings"


def _mock_httpx_client(embedding: list[float]):
    """Return a mock httpx.Client context manager that yields a fixed embedding."""
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"embedding": embedding}

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post = MagicMock(return_value=mock_response)
    return mock_client


class EmbedTextsTests(unittest.TestCase):
    def test_returns_one_vector_per_text(self) -> None:
        from app.core.embeddings import embed_texts
        vec = [0.1, 0.2, 0.3]
        with patch(_OLLAMA_HTTPX, return_value=_mock_httpx_client(vec)):
            results = embed_texts(["hello", "world"], input_type="passage")
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], vec)
        self.assertEqual(results[1], vec)

    def test_applies_passage_prefix_when_enabled(self) -> None:
        from app.core.embeddings import embed_texts
        captured_prompts: list[str] = []

        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"embedding": [0.1]}

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        def capture_post(path, json):  # noqa: A002
            captured_prompts.append(json["prompt"])
            return mock_response

        mock_client.post = capture_post

        with patch(_OLLAMA_HTTPX, return_value=mock_client):
            with patch(_OLLAMA_SETTINGS) as s:
                s.rag_embed_provider = "ollama"
                s.rag_embed_model = "test-model"
                s.tool_router_use_e5_prefix = True
                s.ollama_base_url = "http://localhost:11434"
                s.ollama_timeout = 30.0
                embed_texts(["hello world"], input_type="passage")

        self.assertEqual(len(captured_prompts), 1)
        self.assertTrue(captured_prompts[0].startswith("passage: "))

    def test_applies_query_prefix_when_enabled(self) -> None:
        from app.core.embeddings import embed_texts
        captured_prompts: list[str] = []

        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"embedding": [0.1]}

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        def capture_post(path, json):  # noqa: A002
            captured_prompts.append(json["prompt"])
            return mock_response

        mock_client.post = capture_post

        with patch(_OLLAMA_HTTPX, return_value=mock_client):
            with patch(_OLLAMA_SETTINGS) as s:
                s.rag_embed_provider = "ollama"
                s.rag_embed_model = "test-model"
                s.tool_router_use_e5_prefix = True
                s.ollama_base_url = "http://localhost:11434"
                s.ollama_timeout = 30.0
                embed_texts(["user message"], input_type="query")

        self.assertEqual(captured_prompts[0], "query: user message")

    def test_no_prefix_when_disabled(self) -> None:
        from app.core.config import settings as real_settings
        from app.core.embeddings import embed_texts
        captured_prompts: list[str] = []

        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"embedding": [0.1]}

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        def capture_post(path, json):  # noqa: A002
            captured_prompts.append(json["prompt"])
            return mock_response

        mock_client.post = capture_post

        # Patch attributes on the real settings singleton — app.core.embed_providers
        # already holds its own `from app.core.config import settings` reference,
        # so swapping `app.core.config.settings` wholesale (as elsewhere in this
        # file) would not be seen there.
        with patch(_OLLAMA_HTTPX, return_value=mock_client):
            with patch.multiple(
                real_settings,
                rag_embed_provider="ollama",
                rag_embed_model="test-model",
                tool_router_use_e5_prefix=False,
                ollama_base_url="http://localhost:11434",
                ollama_timeout=30.0,
            ):
                embed_texts(["hello"], input_type="query")

        self.assertEqual(captured_prompts[0], "hello")


class TruncateForEmbedTests(unittest.TestCase):
    def test_short_text_unchanged(self) -> None:
        from app.core.embed_providers.ollama import _truncate_words
        text = "one two three"
        self.assertEqual(_truncate_words(text, max_words=10), text)

    def test_long_text_truncated(self) -> None:
        from app.core.embed_providers.ollama import _truncate_words
        words = [f"w{i}" for i in range(20)]
        text = " ".join(words)
        self.assertEqual(_truncate_words(text, max_words=5), " ".join(words[:5]))

    def test_embed_texts_truncates_before_prefix(self) -> None:
        from app.core.embeddings import embed_texts
        captured_prompts: list[str] = []

        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"embedding": [0.1]}

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        def capture_post(path, json):  # noqa: A002
            captured_prompts.append(json["prompt"])
            return mock_response

        mock_client.post = capture_post

        long_text = " ".join(f"word{i}" for i in range(500))
        with patch(_OLLAMA_HTTPX, return_value=mock_client):
            with patch(_OLLAMA_SETTINGS) as s:
                s.rag_embed_provider = "ollama"
                s.rag_embed_model = "test-model"
                s.tool_router_use_e5_prefix = True
                s.ollama_base_url = "http://localhost:11434"
                s.ollama_timeout = 30.0
                embed_texts([long_text], input_type="passage", max_words=3)

        prompt_words = captured_prompts[0].removeprefix("passage: ").split()
        self.assertEqual(len(prompt_words), 3)

    def test_retries_on_context_length_error(self) -> None:
        from app.core.embeddings import embed_texts

        too_long = MagicMock()
        too_long.is_success = False
        too_long.status_code = 500
        too_long.json.return_value = {"error": "the input length exceeds the context length"}
        too_long.text = ""

        ok = MagicMock()
        ok.is_success = True
        ok.json.return_value = {"embedding": [0.5, 0.6]}

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post = MagicMock(side_effect=[too_long, ok])

        with patch(_OLLAMA_HTTPX, return_value=mock_client):
            with patch(_OLLAMA_SETTINGS) as s:
                s.rag_embed_provider = "ollama"
                s.rag_embed_model = "test-model"
                s.tool_router_use_e5_prefix = False
                s.ollama_base_url = "http://localhost:11434"
                s.ollama_timeout = 30.0
                results = embed_texts(["hello world"], input_type="passage")

        self.assertEqual(results, [[0.5, 0.6]])
        self.assertEqual(mock_client.post.call_count, 2)


class CosineSimilarityTests(unittest.TestCase):
    def test_identical_vectors(self) -> None:
        from app.core.embeddings import cosine_similarity
        v = [1.0, 0.0, 0.0]
        self.assertAlmostEqual(cosine_similarity(v, v), 1.0)

    def test_orthogonal_vectors(self) -> None:
        from app.core.embeddings import cosine_similarity
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        self.assertAlmostEqual(cosine_similarity(a, b), 0.0)

    def test_zero_vector_returns_zero(self) -> None:
        from app.core.embeddings import cosine_similarity
        self.assertEqual(cosine_similarity([0.0, 0.0], [1.0, 1.0]), 0.0)

    def test_symmetric(self) -> None:
        from app.core.embeddings import cosine_similarity
        a = [1.0, 2.0, 3.0]
        b = [4.0, 5.0, 6.0]
        self.assertAlmostEqual(cosine_similarity(a, b), cosine_similarity(b, a))


class ProbeEmbedModelTests(unittest.TestCase):
    def test_returns_true_when_ok(self) -> None:
        from app.core.embeddings import probe_embed_model
        vec = [0.1, 0.2]
        with patch(_OLLAMA_HTTPX, return_value=_mock_httpx_client(vec)):
            with patch(_OLLAMA_SETTINGS) as s:
                s.rag_embed_provider = "ollama"
                s.rag_embed_model = "test"
                s.tool_router_use_e5_prefix = True
                s.ollama_base_url = "http://localhost:11434"
                s.ollama_timeout = 30.0
                result = probe_embed_model()
        self.assertTrue(result)

    def test_returns_false_on_error(self) -> None:
        from app.core.embeddings import probe_embed_model
        import httpx

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post = MagicMock(side_effect=httpx.ConnectError("unreachable"))

        with patch(_OLLAMA_HTTPX, return_value=mock_client):
            result = probe_embed_model()
        self.assertFalse(result)
