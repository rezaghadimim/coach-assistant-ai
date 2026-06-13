"""Cross-encoder reranker for the RAG pipeline.

Wraps ``sentence_transformers.CrossEncoder`` as an optional dependency.  When
the ``rag-rerank`` dependency group is not installed the module degrades
gracefully: :func:`rerank` returns the input list sorted by their original
stage-1 score and :func:`probe_rerank_model` returns ``False``.

Typical usage::

    from app.rag.reranker import rerank, probe_rerank_model

    candidates = retrieve(query, top_k=25, ...)       # stage-1 wide pool
    final = rerank(query, candidates, top_k=3)        # reranked top-3

The loaded model is held as a module-level singleton so it is initialised
once at startup (or first call) and reused for every request.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.core.config import settings

if TYPE_CHECKING:
    from app.rag.retriever import RetrievedChunk

logger = logging.getLogger(__name__)

# Module-level singleton — populated by _load_model().
_model = None
_model_name: str = ""
_unavailable: bool = False


def _load_model():
    """Return the loaded CrossEncoder singleton, or None on import failure."""
    global _model, _model_name, _unavailable

    target = settings.rag_rerank_model
    if _model is not None and _model_name == target:
        return _model
    if _unavailable and _model_name == target:
        return None

    try:
        from sentence_transformers import CrossEncoder  # type: ignore[import-untyped]
    except ImportError:
        _model_name = target
        _unavailable = True
        logger.warning(
            "rag rerank: sentence-transformers not installed — "
            "run `uv sync --group rag-rerank` or `pip install sentence-transformers` to enable reranking"
        )
        return None

    try:
        logger.info("rag rerank: loading model %s …", target)
        _model = CrossEncoder(target)
        _model_name = target
        _unavailable = False
        logger.info("rag rerank: model ready | model=%s", target)
        return _model
    except Exception as exc:
        _model_name = target
        _unavailable = True
        logger.warning("rag rerank: model load failed (%s) — falling back to bi-encoder order", exc)
        return None


def probe_rerank_model() -> bool:
    """Return True when the reranker model loads and scores a dummy pair.

    Triggers a model download on first call — avoid in startup hooks and
    Docker health checks; use :func:`rerank_is_loaded` instead.
    """
    model = _load_model()
    if model is None:
        return False
    try:
        model.predict([("probe query", "probe passage")])
        return True
    except Exception as exc:
        logger.warning("rag rerank: probe failed (%s)", exc)
        return False


def rerank_dependency_installed() -> bool:
    """Return True when sentence-transformers is importable (no model load)."""
    try:
        import sentence_transformers  # noqa: F401
        return True
    except ImportError:
        return False


def rerank_is_loaded() -> bool:
    """Return True when the CrossEncoder singleton is already in memory."""
    return _model is not None and _model_name == settings.rag_rerank_model


def rerank(
    query: str,
    chunks: list[RetrievedChunk],
    *,
    top_k: int,
) -> list[RetrievedChunk]:
    """Rerank *chunks* against *query* using a cross-encoder and return top_k.

    If the model is unavailable or scoring fails, the input list is returned
    sorted by original stage-1 score (no exception raised).

    Args:
        query:   The coach's message / search query.
        chunks:  Candidate pool from stage-1 retrieval.
        top_k:   Maximum number of chunks to return after reranking.

    Returns:
        A list of :class:`~app.rag.retriever.RetrievedChunk` with ``score``
        replaced by the cross-encoder relevance score, sorted descending.
    """
    if not chunks:
        return []

    model = _load_model()
    if model is None:
        logger.debug("rag rerank: model unavailable — returning stage-1 order")
        return chunks[:top_k]

    max_chars = settings.rag_rerank_max_passage_chars
    batch_size = settings.rag_rerank_batch_size

    # Build (query, passage) pairs with optional passage truncation.
    pairs = [(query, chunk.text[:max_chars]) for chunk in chunks]

    try:
        scores: list[float] = []
        for start in range(0, len(pairs), batch_size):
            batch = pairs[start: start + batch_size]
            batch_scores = model.predict(batch)
            scores.extend(float(s) for s in batch_scores)
    except Exception as exc:
        logger.warning("rag rerank: scoring failed (%s) — returning stage-1 order", exc)
        return chunks[:top_k]

    # Pair chunks with their rerank scores, sort descending.
    scored = sorted(zip(scores, chunks), key=lambda t: t[0], reverse=True)

    # Rebuild RetrievedChunk with overwritten score (frozen dataclass — use replace).
    from dataclasses import replace

    reranked = [replace(chunk, score=score) for score, chunk in scored]

    logger.info(
        "rag rerank | candidates=%d final=%d top_scores=%s",
        len(chunks),
        min(top_k, len(reranked)),
        [round(c.score, 3) for c in reranked[:top_k]],
    )

    return reranked[:top_k]
