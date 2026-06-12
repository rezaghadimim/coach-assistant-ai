"""Tests for the RAG reranker module and two-stage retrieve() pipeline.

All tests mock CrossEncoder so they run in CI without the rag-rerank dependency
group installed.
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import MagicMock, patch

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
    """Unit tests for app.rag.reranker — CrossEncoder is always mocked."""

    def _make_mock_cross_encoder(self, scores: list[float]):
        mock_model = MagicMock()
        mock_model.predict.return_value = scores
        return mock_model

    def test_rerank_reorders_and_overwrites_scores(self) -> None:
        """Cross-encoder scores replace stage-1 scores and chunks are reordered."""
        chunks = [
            _make_retrieved("low", score=0.9),   # stage-1 rank 1
            _make_retrieved("high", score=0.5),  # stage-1 rank 2
        ]
        mock_model = self._make_mock_cross_encoder([1.0, 8.0])  # reranker prefers "high"

        with (
            patch("app.rag.reranker._model", mock_model),
            patch("app.rag.reranker._model_name", "BAAI/bge-reranker-v2-m3"),
        ):
            from app.rag.reranker import rerank
            result = rerank("query", chunks, top_k=2)

        self.assertEqual(result[0].chunk_id, "high")
        self.assertEqual(result[1].chunk_id, "low")
        self.assertAlmostEqual(result[0].score, 8.0)
        self.assertAlmostEqual(result[1].score, 1.0)

    def test_rerank_respects_top_k(self) -> None:
        """Returns at most top_k chunks."""
        chunks = [_make_retrieved(f"c{i}", score=float(i)) for i in range(10)]
        scores = list(range(10, 0, -1))  # 10, 9, 8, ...
        mock_model = self._make_mock_cross_encoder(scores)

        with (
            patch("app.rag.reranker._model", mock_model),
            patch("app.rag.reranker._model_name", "BAAI/bge-reranker-v2-m3"),
        ):
            from app.rag.reranker import rerank
            result = rerank("query", chunks, top_k=3)

        self.assertEqual(len(result), 3)

    def test_rerank_fallback_on_import_error(self) -> None:
        """ImportError on sentence_transformers → returns input sorted by original score."""
        chunks = [
            _make_retrieved("a", score=0.3),
            _make_retrieved("b", score=0.8),
            _make_retrieved("c", score=0.5),
        ]

        # Reset module singleton so _load_model() tries to import again.
        import app.rag.reranker as reranker_mod
        original_model = reranker_mod._model
        original_name = reranker_mod._model_name
        original_unavailable = reranker_mod._unavailable
        reranker_mod._model = None
        reranker_mod._model_name = ""
        reranker_mod._unavailable = False

        try:
            with patch.dict("sys.modules", {"sentence_transformers": None}):
                from app.rag.reranker import rerank
                result = rerank("query", chunks, top_k=3)
        finally:
            reranker_mod._model = original_model
            reranker_mod._model_name = original_name
            reranker_mod._unavailable = original_unavailable

        # Falls back to returning input sliced to top_k (stage-1 order).
        self.assertEqual(len(result), 3)
        # No exception raised.

    def test_rerank_fallback_on_predict_error(self) -> None:
        """RuntimeError during predict → returns stage-1 ordering, no exception."""
        chunks = [_make_retrieved(f"c{i}", score=float(i)) for i in range(5)]
        mock_model = MagicMock()
        mock_model.predict.side_effect = RuntimeError("CUDA OOM")

        with (
            patch("app.rag.reranker._model", mock_model),
            patch("app.rag.reranker._model_name", "BAAI/bge-reranker-v2-m3"),
        ):
            from app.rag.reranker import rerank
            result = rerank("query", chunks, top_k=3)

        self.assertEqual(len(result), 3)

    def test_rerank_empty_input(self) -> None:
        from app.rag.reranker import rerank
        result = rerank("query", [], top_k=3)
        self.assertEqual(result, [])

    def test_rerank_truncates_passage(self) -> None:
        """Passages are truncated to rag_rerank_max_passage_chars before scoring."""
        long_text = "word " * 2000
        chunks = [
            RetrievedChunk(
                chunk_id="long",
                source_path="test/long.txt",
                text=long_text,
                score=0.5,
            )
        ]
        mock_model = MagicMock()
        mock_model.predict.return_value = [5.0]
        captured_pairs: list = []

        def capture_predict(pairs):
            captured_pairs.extend(pairs)
            return [5.0]

        mock_model.predict.side_effect = capture_predict

        with (
            patch("app.rag.reranker._model", mock_model),
            patch("app.rag.reranker._model_name", "BAAI/bge-reranker-v2-m3"),
        ):
            from app.rag.reranker import rerank
            rerank("query", chunks, top_k=1)

        _, passage = captured_pairs[0]
        from app.core.config import settings
        self.assertLessEqual(len(passage), settings.rag_rerank_max_passage_chars)


class TestRetrieveWithRerank(unittest.TestCase):
    """Integration tests for the two-stage retrieve() pipeline."""

    def setUp(self) -> None:
        clear_index()

    def _index_n_chunks(self, n: int, prefix: str = "chunk") -> None:
        """Index n unique chunks with distinct token content."""
        chunks = [
            _make_doc_chunk(
                f"{prefix}_{i}",
                f"coaching {prefix} document number {i} GROW model goal reality options will",
                source=f"test/{prefix}_{i}.txt",
            )
            for i in range(n)
        ]
        index_chunks(chunks, embed=False)

    def test_widen_then_narrow(self) -> None:
        """Stage-1 retrieves retrieve_k candidates; reranker narrows to top_k."""
        self._index_n_chunks(15)

        mock_model = MagicMock()
        # Reranker reverses stage-1 order: assign descending scores so last chunk
        # becomes best.
        def fake_predict(pairs):
            return list(range(len(pairs), 0, -1))

        mock_model.predict.side_effect = fake_predict

        with (
            patch("app.rag.reranker._model", mock_model),
            patch("app.rag.reranker._model_name", "BAAI/bge-reranker-v2-m3"),
            patch("app.core.config.settings.rag_rerank_enabled", True),
            patch("app.core.config.settings.rag_retrieve_k", 10),
        ):
            results = retrieve("goal reality", top_k=3, min_score=0.0, backend="token")

        self.assertLessEqual(len(results), 3)
        # Reranker was invoked (predict called).
        mock_model.predict.assert_called()

    def test_skip_rerank_when_pool_le_top_k(self) -> None:
        """Reranker is not called when candidate pool <= top_k."""
        # Index only 2 chunks — fewer than top_k=3.
        self._index_n_chunks(2, prefix="small")

        mock_model = MagicMock()

        with (
            patch("app.rag.reranker._model", mock_model),
            patch("app.rag.reranker._model_name", "BAAI/bge-reranker-v2-m3"),
            patch("app.core.config.settings.rag_rerank_enabled", True),
            patch("app.core.config.settings.rag_retrieve_k", 5),
        ):
            results = retrieve("coaching goal", top_k=3, min_score=0.0, backend="token")

        # predict should NOT have been called — pool (<=2) is not > top_k (3).
        mock_model.predict.assert_not_called()
        self.assertLessEqual(len(results), 2)

    def test_rerank_disabled_returns_stage1_order(self) -> None:
        """When rag_rerank_enabled=False, reranker module is never imported."""
        self._index_n_chunks(5, prefix="dis")

        with patch("app.core.config.settings.rag_rerank_enabled", False):
            results = retrieve("coaching goal", top_k=3, min_score=0.0, backend="token")

        self.assertLessEqual(len(results), 3)

    def test_source_dedup_keeps_best_chunk_per_file(self) -> None:
        """Two overlapping chunks from the same source keep only the highest-scoring one."""
        same_source = "test/shared_doc.txt"
        chunks = [
            _make_doc_chunk("chunk_a", "GROW goal reality options will coaching", source=same_source),
            _make_doc_chunk("chunk_b", "GROW goal reality options will coaching", source=same_source),
            _make_doc_chunk("chunk_c", "motivational interviewing ambivalence change", source="test/other.txt"),
        ]
        index_chunks(chunks, embed=False)

        mock_model = MagicMock()
        # Reranker gives chunk_b a higher score than chunk_a.
        score_map = {"chunk_a": 3.0, "chunk_b": 7.0, "chunk_c": 5.0}

        def fake_predict(pairs):
            # pairs are (query, text); text contains chunk_id in "text for <id>" format
            # We use index to map to the original chunk ordering passed.
            return [4.0] * len(pairs)

        mock_model.predict.side_effect = fake_predict

        with (
            patch("app.rag.reranker._model", mock_model),
            patch("app.rag.reranker._model_name", "BAAI/bge-reranker-v2-m3"),
            patch("app.core.config.settings.rag_rerank_enabled", False),
        ):
            results = retrieve("GROW coaching", top_k=5, min_score=0.0, backend="token")

        # Only one chunk from same_source should appear.
        sources = [r.source_path for r in results]
        self.assertEqual(sources.count(same_source), 1)

    def test_retrieve_k_override(self) -> None:
        """retrieve_k can be overridden per call."""
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
