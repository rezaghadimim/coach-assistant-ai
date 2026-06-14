"""Tests for the RAG reranker module and two-stage retrieve() pipeline.

Ollama HTTP calls are mocked so tests run in CI without a local reranker model.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.rag.ingest import DocumentChunk
from app.rag.retriever import (
    RetrievedChunk,
    clear_index,
    index_chunks,
    retrieve,
)


def _make_doc_chunk(chunk_id: str, text: str, source: str = "") -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        source_path=source or f"test/{chunk_id}.txt",
        text=text,
        start_token=0,
        end_token=len(text.split()),
    )


def _make_retrieved(chunk_id: str, score: float, source: str = "") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        source_path=source or f"test/{chunk_id}.txt",
        text=f"text for {chunk_id}",
        score=score,
    )


class TestRerankerModule(unittest.TestCase):
    """Unit tests for app.rag.reranker — Ollama client is always mocked."""

    def test_rerank_reorders_and_overwrites_scores(self) -> None:
        chunks = [
            _make_retrieved("low", score=0.9),
            _make_retrieved("high", score=0.5),
        ]

        with patch(
            "app.rag.reranker.rerank_documents",
            return_value=[1.0, 8.0],
        ):
            from app.rag.reranker import rerank

            result = rerank("query", chunks, top_k=2)

        self.assertEqual(result[0].chunk_id, "high")
        self.assertEqual(result[1].chunk_id, "low")
        self.assertAlmostEqual(result[0].score, 8.0)
        self.assertAlmostEqual(result[1].score, 1.0)

    def test_rerank_respects_top_k(self) -> None:
        chunks = [_make_retrieved(f"c{i}", score=float(i)) for i in range(10)]
        scores = list(range(10, 0, -1))

        with patch("app.rag.reranker.rerank_documents", return_value=scores):
            from app.rag.reranker import rerank

            result = rerank("query", chunks, top_k=3)

        self.assertEqual(len(result), 3)

    def test_rerank_fallback_on_ollama_error(self) -> None:
        chunks = [
            _make_retrieved("a", score=0.3),
            _make_retrieved("b", score=0.8),
            _make_retrieved("c", score=0.5),
        ]

        with patch(
            "app.rag.reranker.rerank_documents",
            side_effect=RuntimeError("Ollama unreachable"),
        ):
            from app.rag.reranker import rerank

            result = rerank("query", chunks, top_k=3)

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0].chunk_id, "a")

    def test_rerank_empty_input(self) -> None:
        from app.rag.reranker import rerank

        result = rerank("query", [], top_k=3)
        self.assertEqual(result, [])

    def test_rerank_truncates_passage(self) -> None:
        long_text = "word " * 2000
        chunks = [
            RetrievedChunk(
                chunk_id="long",
                source_path="test/long.txt",
                text=long_text,
                score=0.5,
            )
        ]
        captured_documents: list[str] = []

        def capture_rerank(_query: str, documents: list[str], **_kwargs):
            captured_documents.extend(documents)
            return [5.0]

        with patch("app.rag.reranker.rerank_documents", side_effect=capture_rerank):
            from app.rag.reranker import rerank

            rerank("query", chunks, top_k=1)

        from app.core.config import settings

        self.assertEqual(len(captured_documents), 1)
        self.assertLessEqual(len(captured_documents[0]), settings.rag_rerank_max_passage_chars)


class TestRetrieveWithRerank(unittest.TestCase):
    """Integration tests for the two-stage retrieve() pipeline."""

    def setUp(self) -> None:
        clear_index()

    def _index_n_chunks(self, n: int, prefix: str = "chunk") -> None:
        chunks = [
            _make_doc_chunk(
                f"{prefix}_{i}",
                f"coaching {prefix} document number {i} GROW model goal reality options will",
                source=f"test/{prefix}_{i}.txt",
            )
            for i in range(n)
        ]
        index_chunks(chunks, embed=False)

    def test_widen_then_narrow_reorders_by_rerank_scores(self) -> None:
        self._index_n_chunks(15)

        def fake_rerank(_query: str, documents: list[str], **_kwargs):
            # Boost the last stage-1 candidate so reranking reverses stage-1 order.
            n = len(documents)
            return [float(i) / n for i in range(1, n + 1)]

        with patch("app.core.config.settings.rag_retrieve_k", 10):
            with patch("app.core.config.settings.rag_rerank_enabled", False):
                stage1 = retrieve("goal reality", top_k=3, min_score=0.0, backend="token")

            with (
                patch("app.rag.reranker.rerank_documents", side_effect=fake_rerank),
                patch("app.core.config.settings.rag_rerank_enabled", True),
            ):
                reranked = retrieve("goal reality", top_k=3, min_score=0.0, backend="token")

        self.assertLessEqual(len(reranked), 3)
        if len(stage1) >= 1 and len(reranked) >= 1:
            self.assertNotEqual(
                stage1[0].chunk_id,
                reranked[0].chunk_id,
                "rerank should change the top result when scores invert",
            )

    def test_skip_rerank_when_pool_le_top_k(self) -> None:
        self._index_n_chunks(2, prefix="small")

        with (
            patch("app.rag.reranker.rerank_documents") as mock_rerank,
            patch("app.core.config.settings.rag_rerank_enabled", True),
            patch("app.core.config.settings.rag_retrieve_k", 5),
        ):
            results = retrieve("coaching goal", top_k=3, min_score=0.0, backend="token")

        mock_rerank.assert_not_called()
        self.assertLessEqual(len(results), 2)

    def test_rerank_disabled_returns_stage1_order(self) -> None:
        self._index_n_chunks(5, prefix="dis")

        with patch("app.core.config.settings.rag_rerank_enabled", False):
            results = retrieve("coaching goal", top_k=3, min_score=0.0, backend="token")

        self.assertLessEqual(len(results), 3)

    def test_source_dedup_keeps_best_chunk_per_file(self) -> None:
        same_source = "test/shared_doc.txt"
        chunks = [
            _make_doc_chunk("chunk_a", "GROW goal reality options will coaching", source=same_source),
            _make_doc_chunk("chunk_b", "GROW goal reality options will coaching", source=same_source),
            _make_doc_chunk("chunk_c", "motivational interviewing ambivalence change", source="test/other.txt"),
        ]
        index_chunks(chunks, embed=False)

        with patch("app.core.config.settings.rag_rerank_enabled", False):
            results = retrieve("GROW coaching", top_k=5, min_score=0.0, backend="token")

        sources = [r.source_path for r in results]
        self.assertEqual(sources.count(same_source), 1)

    def test_retrieve_k_override(self) -> None:
        self._index_n_chunks(20, prefix="ovr")

        with patch("app.core.config.settings.rag_rerank_enabled", False):
            results = retrieve(
                "coaching goal",
                top_k=3,
                min_score=0.0,
                backend="token",
                retrieve_k=5,
            )

        self.assertLessEqual(len(results), 3)


if __name__ == "__main__":
    unittest.main()
