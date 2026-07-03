"""RAG stage-2 reranker — local cross-encoder scoring.

Delegates to :mod:`app.core.rerank`, which runs an ONNX cross-encoder
in-process via fastembed (no Ollama, no PyTorch).  Falls back to stage-1
ordering whenever scoring is unavailable.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from app.core.config import settings
from app.core.observability import log_step
from app.core.rerank import (
    fastembed_installed,
    probe_rerank_model,
    rerank_documents,
    rerank_probe_cached,
)

if TYPE_CHECKING:
    from app.rag.retriever import RetrievedChunk

logger = logging.getLogger(__name__)

__all__ = ["rerank", "rerank_dependency_installed", "rerank_is_loaded", "probe_rerank_model"]


def rerank_dependency_installed() -> bool:
    """Return True when the local reranker dependency (fastembed) is installed."""
    return fastembed_installed()


def rerank_is_loaded() -> bool:
    """Return True after the cross-encoder has loaded and scored at least once."""
    return rerank_probe_cached() is True


def rerank(
    query: str,
    chunks: list[RetrievedChunk],
    *,
    top_k: int,
) -> list[RetrievedChunk]:
    """Rerank *chunks* against *query* with the local cross-encoder; return top_k.

    Raises on any scoring failure so the caller can fall back to stage-1
    ordering with the original stage-1 scores intact.  Returning the input
    chunks from here instead would hide the failure: the caller would apply
    ``rag_rerank_min_score`` to scores that are not cross-encoder scores.
    """
    if not chunks:
        return []

    max_chars = settings.rag_rerank_max_passage_chars
    documents = [chunk.text[:max_chars] for chunk in chunks]

    scores = rerank_documents(
        query,
        documents,
        model=settings.rag_rerank_model,
        batch_size=settings.rag_rerank_batch_size,
        max_passage_chars=max_chars,
    )

    scored = sorted(zip(scores, chunks), key=lambda t: t[0], reverse=True)
    reranked = [replace(chunk, score=score) for score, chunk in scored]
    final = reranked[:top_k]

    log_step(logger, "rag.rerank", "ok",
             model=settings.rag_rerank_model,
             candidates=len(chunks), final=len(final),
             top_score=round(final[0].score, 3) if final else 0.0)

    return final
