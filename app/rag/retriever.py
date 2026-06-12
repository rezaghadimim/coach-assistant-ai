"""Local retriever for indexed coaching document chunks.

Supports two retrieval backends:
  - "embedding": dense cosine similarity using the E5 embed model (semantic).
  - "token":     sparse TF cosine similarity (keyword, offline-safe).
  - "auto":      uses embedding when the embed model probe passes, else token.

Chunk embeddings are cached on disk so application restarts skip re-embedding
when content is unchanged. Cache keys are (chunk_id, text-hash) pairs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Literal

from app.core.config import settings
from app.rag.ingest import DocumentChunk, ingest_documents_from_dir

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[\w'']+", re.UNICODE)

Backend = Literal["auto", "embedding", "token"]


@dataclass(frozen=True)
class RetrievedChunk:
    """A chunk returned by retrieval, with similarity score."""

    chunk_id: str
    source_path: str
    text: str
    score: float


@dataclass
class _IndexedChunk:
    chunk: DocumentChunk
    tf: Counter[str]
    norm: float
    embedding: list[float] = field(default_factory=list)


_index: list[_IndexedChunk] = []
# Whether the current index has dense embeddings loaded.
_embedding_index_ready: bool = False


def clear_index() -> None:
    """Clear the in-memory index (used by tests and re-ingest)."""
    global _embedding_index_ready
    _index.clear()
    _embedding_index_ready = False


def index_chunks(
    chunks: Iterable[DocumentChunk],
    *,
    reset: bool = False,
    embed: bool = False,
    cache_path: str | None = None,
) -> int:
    """Index document chunks and return count of newly indexed chunks.

    Args:
        chunks: Iterable of DocumentChunk objects to index.
        reset:  Clear existing index before indexing.
        embed:  Whether to compute and store dense embeddings.
        cache_path: Path to on-disk embedding cache JSON. When provided,
                    embeddings are loaded from cache before calling the embed
                    model, and newly computed embeddings are written back.
    """
    global _embedding_index_ready
    if reset:
        clear_index()

    chunk_list = list(chunks)
    cache: dict[str, list[float]] = {}
    if embed and cache_path:
        cache = _load_cache(cache_path)

    added = 0
    newly_embedded: dict[str, list[float]] = {}

    for chunk in chunk_list:
        tokens = _tokenize(chunk.text)
        if not tokens:
            continue
        tf = Counter(tokens)
        norm = math.sqrt(sum(v * v for v in tf.values()))
        embedding: list[float] = []

        if embed:
            cache_key = _cache_key(chunk)
            if cache_key in cache:
                embedding = cache[cache_key]
            else:
                try:
                    from app.core.embeddings import embed_texts
                    vecs = embed_texts([chunk.text], input_type="passage")
                    embedding = vecs[0] if vecs else []
                    if embedding:
                        newly_embedded[cache_key] = embedding
                except Exception as exc:
                    logger.warning("embed failed for chunk %s: %s", chunk.chunk_id, exc)

        _index.append(_IndexedChunk(chunk=chunk, tf=tf, norm=norm, embedding=embedding))
        added += 1

    if embed:
        has_any_embedding = any(ic.embedding for ic in _index)
        _embedding_index_ready = has_any_embedding
        if newly_embedded and cache_path:
            cache.update(newly_embedded)
            _save_cache(cache_path, cache)
            logger.info("rag: saved %d new embeddings to cache %s", len(newly_embedded), cache_path)

    return added


def ingest_and_index_directory(
    docs_dir: str,
    *,
    chunk_size: int,
    chunk_overlap: int,
    embed: bool = False,
    cache_path: str | None = None,
) -> tuple[int, int]:
    """Chunk all supported docs in a directory and index them."""
    chunks = ingest_documents_from_dir(
        docs_dir,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    docs_count = len({chunk.source_path for chunk in chunks})
    chunks_count = index_chunks(chunks, reset=True, embed=embed, cache_path=cache_path)
    return docs_count, chunks_count


def retrieve(
    query: str,
    *,
    top_k: int = 3,
    min_score: float = 0.05,
    backend: Backend = "auto",
    retrieve_k: int | None = None,
) -> list[RetrievedChunk]:
    """Retrieve top matching chunks for a query from the local index.

    When reranking is enabled (``settings.rag_rerank_enabled``) the pipeline
    runs in two stages:

    1. Stage-1 retrieval — fetch up to ``retrieve_k`` candidates (defaults to
       ``settings.rag_retrieve_k``, typically 25) using bi-encoder or token
       similarity.
    2. Cross-encoder reranking — score all candidates as (query, passage) pairs
       and keep the best ``top_k``.  Falls back to stage-1 order silently when
       the reranker is unavailable.

    Args:
        query:      The coach's message or question.
        top_k:      Maximum number of chunks to return (final context size).
        min_score:  Minimum similarity score threshold applied to stage-1 scores.
                    Also applied to rerank scores after reranking.
        backend:    "auto" | "embedding" | "token".
        retrieve_k: Override the stage-1 candidate pool size.  Defaults to
                    ``settings.rag_retrieve_k``.
    """
    if not _index:
        return []

    use_embedding = _resolve_backend(backend)
    backend_name = "embedding" if use_embedding else "token"

    # Stage-1: fetch a wider candidate pool for reranking.
    candidate_k = retrieve_k if retrieve_k is not None else settings.rag_retrieve_k
    candidate_k = max(candidate_k, top_k)

    if use_embedding:
        candidates = _retrieve_embedding(query, top_k=candidate_k, min_score=min_score)
    else:
        candidates = _retrieve_token(query, top_k=candidate_k, min_score=min_score)

    logger.info(
        "rag retrieve | backend=%s query=%r candidate_k=%d candidates=%d",
        backend_name,
        query[:80],
        candidate_k,
        len(candidates),
    )

    # Stage-2: rerank when enabled and there is something to reorder.
    if settings.rag_rerank_enabled and len(candidates) > top_k:
        try:
            from app.rag.reranker import rerank
            candidates = rerank(query, candidates, top_k=top_k)
        except Exception as exc:
            logger.warning("rag rerank: unexpected error (%s) — using stage-1 order", exc)
            candidates = candidates[:top_k]
    else:
        candidates = candidates[:top_k]

    # Deduplicate: keep only the highest-scoring chunk per source file so that
    # overlapping 512-token windows from the same document don't flood context.
    seen_sources: set[str] = set()
    deduped: list[RetrievedChunk] = []
    for chunk in candidates:
        if chunk.source_path not in seen_sources:
            seen_sources.add(chunk.source_path)
            deduped.append(chunk)

    # Re-apply min_score on final (possibly reranked) scores.
    final = [c for c in deduped if c.score >= min_score][:top_k]

    logger.info(
        "rag retrieve | final=%d scores=%s",
        len(final),
        [(c.chunk_id, round(c.score, 3)) for c in final],
    )
    return final


def format_retrieval_context(chunks: list[RetrievedChunk]) -> str:
    """Format retrieved chunks for inclusion in a system prompt."""
    if not chunks:
        return ""

    lines = ["## Relevant Coaching Knowledge"]
    for index, chunk in enumerate(chunks, start=1):
        lines.append(
            f"[{index}] {chunk.source_path} ({chunk.chunk_id}, score={chunk.score:.2f})"
        )
        lines.append(chunk.text)
        lines.append("")
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Backend implementations
# ---------------------------------------------------------------------------

def _resolve_backend(backend: Backend) -> bool:
    """Return True to use embedding, False to use token cosine."""
    if backend == "embedding":
        return _embedding_index_ready
    if backend == "token":
        return False
    # auto: use embedding when the index was built with embeddings
    return _embedding_index_ready


def _retrieve_embedding(
    query: str,
    *,
    top_k: int,
    min_score: float,
) -> list[RetrievedChunk]:
    try:
        from app.core.embeddings import embed_query, cosine_similarity
        query_vec = embed_query(query)
    except Exception as exc:
        logger.warning("rag: embedding query failed (%s), falling back to token", exc)
        return _retrieve_token(query, top_k=top_k, min_score=min_score)

    scored: list[RetrievedChunk] = []
    for indexed in _index:
        if not indexed.embedding:
            continue
        score = cosine_similarity(query_vec, indexed.embedding)
        if score < min_score:
            continue
        scored.append(
            RetrievedChunk(
                chunk_id=indexed.chunk.chunk_id,
                source_path=indexed.chunk.source_path,
                text=indexed.chunk.text,
                score=score,
            )
        )

    scored.sort(key=lambda item: item.score, reverse=True)
    return scored[:top_k]


def _retrieve_token(
    query: str,
    *,
    top_k: int,
    min_score: float,
) -> list[RetrievedChunk]:
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    query_tf = Counter(query_tokens)
    query_norm = math.sqrt(sum(v * v for v in query_tf.values()))
    if query_norm == 0.0:
        return []

    scored: list[RetrievedChunk] = []
    for indexed in _index:
        score = _tf_cosine(query_tf, query_norm, indexed.tf, indexed.norm)
        if score < min_score:
            continue
        scored.append(
            RetrievedChunk(
                chunk_id=indexed.chunk.chunk_id,
                source_path=indexed.chunk.source_path,
                text=indexed.chunk.text,
                score=score,
            )
        )

    scored.sort(key=lambda item: item.score, reverse=True)
    return scored[:top_k]


# ---------------------------------------------------------------------------
# Embedding cache helpers
# ---------------------------------------------------------------------------

def _cache_key(chunk: DocumentChunk) -> str:
    text_hash = hashlib.sha256(chunk.text.encode()).hexdigest()[:16]
    return f"{chunk.chunk_id}::{text_hash}"


def _load_cache(cache_path: str) -> dict[str, list[float]]:
    path = Path(cache_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception as exc:
        logger.warning("rag: could not load embedding cache %s: %s", cache_path, exc)
    return {}


def _save_cache(cache_path: str, cache: dict[str, list[float]]) -> None:
    path = Path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(cache), encoding="utf-8")
    except Exception as exc:
        logger.warning("rag: could not write embedding cache %s: %s", cache_path, exc)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _tf_cosine(
    query_tf: Counter[str],
    query_norm: float,
    doc_tf: Counter[str],
    doc_norm: float,
) -> float:
    if doc_norm == 0.0:
        return 0.0
    dot = sum(query_weight * doc_tf.get(token, 0) for token, query_weight in query_tf.items())
    if dot == 0.0:
        return 0.0
    return dot / (query_norm * doc_norm)


def _tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in _TOKEN_RE.finditer(text)]
