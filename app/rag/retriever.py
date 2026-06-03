"""Simple local retriever for indexed coaching document chunks."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from app.rag.ingest import DocumentChunk, ingest_documents_from_dir

_TOKEN_RE = re.compile(r"[\w’']+", re.UNICODE)


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


_index: list[_IndexedChunk] = []


def clear_index() -> None:
    """Clear current in-memory index (used by tests and re-ingest)."""
    _index.clear()


def index_chunks(chunks: Iterable[DocumentChunk], *, reset: bool = False) -> int:
    """Index document chunks and return count of newly indexed chunks."""
    if reset:
        clear_index()

    added = 0
    for chunk in chunks:
        tokens = _tokenize(chunk.text)
        if not tokens:
            continue
        tf = Counter(tokens)
        norm = math.sqrt(sum(value * value for value in tf.values()))
        _index.append(_IndexedChunk(chunk=chunk, tf=tf, norm=norm))
        added += 1
    return added


def ingest_and_index_directory(
    docs_dir: str,
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> tuple[int, int]:
    """Chunk all supported docs in a directory and index them."""
    chunks = ingest_documents_from_dir(
        docs_dir,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    docs_count = len({chunk.source_path for chunk in chunks})
    chunks_count = index_chunks(chunks, reset=True)
    return docs_count, chunks_count


def retrieve(
    query: str,
    *,
    top_k: int = 3,
    min_score: float = 0.05,
) -> list[RetrievedChunk]:
    """Retrieve top matching chunks for a query from the local index."""
    query_tokens = _tokenize(query)
    if not query_tokens or not _index:
        return []

    query_tf = Counter(query_tokens)
    query_norm = math.sqrt(sum(value * value for value in query_tf.values()))
    if query_norm == 0.0:
        return []

    scored: list[RetrievedChunk] = []
    for indexed in _index:
        score = _cosine_similarity(query_tf, query_norm, indexed.tf, indexed.norm)
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


def _cosine_similarity(
    query_tf: Counter[str],
    query_norm: float,
    doc_tf: Counter[str],
    doc_norm: float,
) -> float:
    if doc_norm == 0.0:
        return 0.0
    dot = 0.0
    for token, query_weight in query_tf.items():
        dot += query_weight * doc_tf.get(token, 0)
    if dot == 0.0:
        return 0.0
    return dot / (query_norm * doc_norm)


def _tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in _TOKEN_RE.finditer(text)]
