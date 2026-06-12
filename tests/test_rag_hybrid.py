"""Tests for hybrid RAG retrieval (embedding + token fallback) and disk cache."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.rag.retriever import (
    clear_index,
    index_chunks,
    ingest_and_index_directory,
    retrieve,
    _load_cache,
    _save_cache,
    _cache_key,
    _embedding_index_ready,
)
from app.rag.ingest import DocumentChunk


def _make_chunk(chunk_id: str, text: str) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        source_path=f"test/{chunk_id}.txt",
        text=text,
        start_token=0,
        end_token=len(text.split()),
    )


class TestTokenRetrieval(unittest.TestCase):
    """Token cosine retrieval still works after refactor."""

    def setUp(self) -> None:
        clear_index()

    def test_token_retrieval_returns_matches(self) -> None:
        chunks = [
            _make_chunk("grow", "GROW model goal reality options will"),
            _make_chunk("mi", "motivational interviewing ambivalence change"),
        ]
        index_chunks(chunks, embed=False)
        results = retrieve("goal and reality", top_k=2, min_score=0.0, backend="token")
        self.assertTrue(results)
        self.assertEqual(results[0].chunk_id, "grow")

    def test_token_retrieval_empty_query(self) -> None:
        chunks = [_make_chunk("c1", "coaching questions")]
        index_chunks(chunks, embed=False)
        results = retrieve("", top_k=2, min_score=0.0, backend="token")
        self.assertEqual(results, [])

    def test_token_retrieval_empty_index(self) -> None:
        results = retrieve("anything", top_k=2, min_score=0.0, backend="token")
        self.assertEqual(results, [])

    def test_min_score_filter(self) -> None:
        chunks = [_make_chunk("unrelated", "pizza recipe ingredients flour")]
        index_chunks(chunks, embed=False)
        results = retrieve("GROW coaching framework", top_k=3, min_score=0.99, backend="token")
        self.assertEqual(results, [])


class TestEmbeddingRetrieval(unittest.TestCase):
    """Embedding-backed retrieval with mocked embed functions."""

    def setUp(self) -> None:
        clear_index()

    def _fake_embed_texts(self, texts, *, input_type="passage", model=None):
        # Returns a simple 3-dim vector based on text length for testing.
        return [[len(t) / 100.0, 0.5, 0.1] for t in texts]

    def _fake_embed_query(self, text, *, model=None):
        return [len(text) / 100.0, 0.5, 0.1]

    def _fake_cosine_similarity(self, a, b):
        # Dot product of simple vectors — sufficient for testing routing logic.
        return sum(x * y for x, y in zip(a, b))

    def test_embedding_retrieval_uses_dense_vectors(self) -> None:
        chunks = [
            _make_chunk("short", "hi"),
            _make_chunk("medium", "This is a medium length coaching document about GROW"),
        ]
        with patch("app.core.embeddings.embed_texts", side_effect=self._fake_embed_texts):
            count = index_chunks(chunks, embed=True)

        self.assertEqual(count, 2)

        with (
            patch("app.core.embeddings.embed_query", side_effect=self._fake_embed_query),
            patch("app.core.embeddings.cosine_similarity", side_effect=self._fake_cosine_similarity),
        ):
            results = retrieve("medium length text", top_k=2, min_score=0.0, backend="embedding")

        self.assertTrue(results)

    def test_embedding_fallback_to_token_on_query_error(self) -> None:
        """When embed_query raises, retrieve() silently falls back to token."""
        chunks = [_make_chunk("grow", "GROW model goal reality options will")]
        with patch("app.core.embeddings.embed_texts", side_effect=self._fake_embed_texts):
            index_chunks(chunks, embed=True)

        with patch(
            "app.core.embeddings.embed_query",
            side_effect=ConnectionError("Ollama unavailable"),
        ):
            results = retrieve("goal reality", top_k=1, min_score=0.0, backend="embedding")

        # Falls back to token — should still return results.
        self.assertTrue(results)

    def test_auto_backend_uses_token_when_no_embeddings(self) -> None:
        """auto backend uses token when index was built without embeddings."""
        chunks = [_make_chunk("grow", "GROW model goal reality options will")]
        index_chunks(chunks, embed=False)
        results = retrieve("goal", top_k=1, min_score=0.0, backend="auto")
        # Should return token results without error.
        self.assertTrue(results)


class TestEmbeddingCache(unittest.TestCase):
    """Disk cache for chunk embeddings."""

    def setUp(self) -> None:
        clear_index()

    def test_cache_write_and_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "cache.json")
            data = {"chunk::abc": [0.1, 0.2, 0.3]}
            _save_cache(path, data)
            loaded = _load_cache(path)
            self.assertEqual(loaded, data)

    def test_cache_load_missing_file(self) -> None:
        result = _load_cache("/nonexistent/path/cache.json")
        self.assertEqual(result, {})

    def test_cache_load_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("not valid json", encoding="utf-8")
            result = _load_cache(str(path))
            self.assertEqual(result, {})

    def test_index_writes_new_embeddings_to_cache(self) -> None:
        def fake_embed(texts, *, input_type="passage", model=None):
            return [[0.1, 0.2, 0.3] for _ in texts]

        chunks = [_make_chunk("c1", "GROW coaching model")]
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = str(Path(tmp) / "cache.json")
            with patch("app.core.embeddings.embed_texts", side_effect=fake_embed):
                index_chunks(chunks, embed=True, cache_path=cache_path)

            cache = _load_cache(cache_path)
            self.assertGreater(len(cache), 0)
            self.assertIsInstance(list(cache.values())[0], list)

    def test_index_reuses_cached_embeddings(self) -> None:
        """Second ingest does not call embed_texts for already-cached chunks."""
        chunks = [_make_chunk("c1", "GROW coaching model")]
        cache_key = _cache_key(chunks[0])

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = str(Path(tmp) / "cache.json")
            _save_cache(cache_path, {cache_key: [0.9, 0.1, 0.0]})

            with patch("app.core.embeddings.embed_texts") as mock_embed:
                mock_embed.return_value = [[0.5, 0.5, 0.0]]
                clear_index()
                index_chunks(chunks, embed=True, cache_path=cache_path)
                mock_embed.assert_not_called()


class TestIngestAndIndexDirectory(unittest.TestCase):
    """ingest_and_index_directory passes embed/cache args through."""

    def setUp(self) -> None:
        clear_index()

    def test_ingest_directory_token_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "doc.txt").write_text("GROW model coaching", encoding="utf-8")
            docs, chunks = ingest_and_index_directory(
                tmp, chunk_size=20, chunk_overlap=2, embed=False
            )
            self.assertEqual(docs, 1)
            self.assertGreaterEqual(chunks, 1)

    def test_ingest_directory_embedding_backend(self) -> None:
        def fake_embed(texts, *, input_type="passage", model=None):
            return [[0.1, 0.2] for _ in texts]

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "doc.txt").write_text("Coaching with MI and GROW", encoding="utf-8")
            with (
                tempfile.TemporaryDirectory() as cache_tmp,
                patch("app.core.embeddings.embed_texts", side_effect=fake_embed),
            ):
                cache_path = str(Path(cache_tmp) / "rag.json")
                docs, chunks = ingest_and_index_directory(
                    tmp, chunk_size=20, chunk_overlap=2,
                    embed=True, cache_path=cache_path,
                )
                self.assertEqual(docs, 1)
                self.assertGreaterEqual(chunks, 1)
                # Cache should have been written
                self.assertTrue(Path(cache_path).exists())


if __name__ == "__main__":
    unittest.main()
