"""Tests for hybrid RRF stage-1 retrieval."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.rag.ingest import DocumentChunk
from app.rag.retriever import clear_index, index_chunks, retrieve


def _make_doc_chunk(chunk_id: str, text: str) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        source_path=f"test/{chunk_id}.txt",
        text=text,
        start_token=0,
        end_token=len(text.split()),
    )


class TestHybridRRF(unittest.TestCase):
    def setUp(self) -> None:
        clear_index()

    def test_rrf_promotes_token_exact_match(self) -> None:
        chunks = [
            _make_doc_chunk("embed_only", "coaching general motivation support"),
            _make_doc_chunk("token_hit", "GROW model goal reality options will framework"),
        ]
        index_chunks(chunks, embed=True)

        with (
            patch("app.rag.retriever._embedding_index_ready", True),
            patch("app.core.config.settings.rag_hybrid_rrf_enabled", True),
            patch("app.core.config.settings.rag_rerank_enabled", False),
            patch(
                "app.rag.retriever._retrieve_embedding",
                return_value=[],
            ),
            patch(
                "app.rag.retriever._retrieve_token",
                return_value=[
                    __import__("app.rag.retriever", fromlist=["RetrievedChunk"]).RetrievedChunk(
                        chunk_id="token_hit",
                        source_path="test/token_hit.txt",
                        text=chunks[1].text,
                        score=0.8,
                    )
                ],
            ),
        ):
            results = retrieve("GROW model", top_k=1, min_score=0.0, backend="embedding")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].chunk_id, "token_hit")


if __name__ == "__main__":
    unittest.main()
