"""End-to-end tests for the local fastembed cross-encoder reranker.

These tests load the real ONNX model and exercise the full retrieve() pipeline.
They are skipped when fastembed is not installed, the model is not cached yet,
or a network timeout prevents download (avoids flaky CI / offline runs).

Set ``RUN_RERANK_INTEGRATION=1`` to force running even when the cache is empty
(will download ~1 GB on first run).
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import settings
from app.core.rerank import fastembed_installed, rerank_documents
from app.rag.ingest import DocumentChunk
from app.rag.retriever import clear_index, index_chunks, retrieve


def _model_cache_populated() -> bool:
    cache_dir = Path(settings.rag_rerank_cache_dir)
    if not cache_dir.is_dir():
        return False
    return any(cache_dir.rglob("*.onnx")) or any(cache_dir.rglob("model.onnx"))


def _integration_enabled() -> bool:
    if os.environ.get("RUN_RERANK_INTEGRATION", "").lower() in {"1", "true", "yes"}:
        return True
    return _model_cache_populated()


def _skip_reason() -> str:
    if not fastembed_installed():
        return "fastembed not installed"
    if not _integration_enabled():
        return (
            "reranker model not cached — set RUN_RERANK_INTEGRATION=1 to download, "
            f"or run once to populate {settings.rag_rerank_cache_dir}/"
        )
    return ""


@unittest.skipIf(bool(_skip_reason()), _skip_reason() or "skipped")
class TestRealCrossEncoder(unittest.TestCase):
    def test_scores_grow_passage_highest(self) -> None:
        query = "What are the four stages of the GROW model?"
        docs = [
            "Motivational interviewing resolves ambivalence using open questions.",
            "The GROW model has four stages: Goal, Reality, Options, and Will.",
            "Homework between sessions reinforces learning with small actions.",
        ]
        scores = rerank_documents(query, docs, batch_size=3)

        self.assertEqual(len(scores), 3)
        for score in scores:
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)

        grow_score = scores[1]
        self.assertGreater(grow_score, scores[0])
        self.assertGreater(grow_score, scores[2])
        self.assertGreater(grow_score, 0.5)

    def test_irrelevant_passage_below_min_score_default(self) -> None:
        from app.core.config import settings

        query = "What are the four stages of the GROW model?"
        docs = [
            "The GROW model has four stages: Goal, Reality, Options, and Will.",
            "Motivational interviewing resolves ambivalence using open questions.",
        ]
        scores = rerank_documents(query, docs, batch_size=2)

        self.assertGreater(scores[0], settings.rag_min_score)
        self.assertLess(scores[1], settings.rag_min_score)


@unittest.skipIf(bool(_skip_reason()), _skip_reason() or "skipped")
class TestRetrievePipelineWithRealReranker(unittest.TestCase):
    def setUp(self) -> None:
        clear_index()

    def test_two_stage_pipeline_reranks_candidates(self) -> None:
        chunks = [
            DocumentChunk(
                chunk_id="mi",
                source_path="test/mi.txt",
                text="Motivational interviewing explores ambivalence and readiness for change.",
                start_token=0,
                end_token=10,
            ),
            DocumentChunk(
                chunk_id="grow",
                source_path="test/grow.txt",
                text="The GROW model structures coaching around Goal Reality Options and Will.",
                start_token=0,
                end_token=12,
            ),
            DocumentChunk(
                chunk_id="homework",
                source_path="test/homework.txt",
                text="Assign homework exercises between coaching sessions to reinforce progress.",
                start_token=0,
                end_token=10,
            ),
            DocumentChunk(
                chunk_id="grow2",
                source_path="test/grow2.txt",
                text="GROW coaching conversations begin by clarifying the client's Goal.",
                start_token=0,
                end_token=10,
            ),
        ]
        index_chunks(chunks, embed=False)

        from app.core.config import settings

        with (
            patch.object(settings, "rag_rerank_enabled", True),
            patch.object(settings, "rag_retrieve_k", 4),
        ):
            results = retrieve(
                "GROW model goal reality options will",
                top_k=2,
                min_score=0.0,
                backend="token",
            )

        self.assertGreaterEqual(len(results), 1)
        grow_sources = {r.source_path for r in results if "grow" in r.source_path}
        self.assertTrue(grow_sources, "expected a GROW chunk in reranked results")
        if len(results) >= 2:
            self.assertIn("grow", results[0].source_path)


if __name__ == "__main__":
    unittest.main()
