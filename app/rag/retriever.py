"""Local retriever for indexed coaching document chunks.

Supports dual indices (framework + collection corpora), pluggable embedding
providers, and two-phase coach retrieval (problem match + expert solutions).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterable, Literal

from app.core.config import settings
from app.core.embed_providers import embed_profile_for_corpus, get_embed_provider
from app.core.observability import log_step
from app.rag.ingest import DocumentChunk, ingest_documents_from_dir

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[\w'']+", re.UNICODE)

Backend = Literal["auto", "embedding", "token"]
CorpusKind = Literal["framework", "collection"]
IndexName = Literal["framework", "collection"]


@dataclass(frozen=True)
class RetrievedChunk:
    """A chunk returned by retrieval, with similarity score."""

    chunk_id: str
    source_path: str
    text: str
    score: float
    collection_id: str | None = None
    person_name: str | None = None
    source_title: str | None = None
    start_sec: float | None = None
    end_sec: float | None = None
    chunk_role: str = "general"
    corpus: str = "framework"


@dataclass(frozen=True)
class CoachRetrievalResult:
    """Structured two-phase retrieval output for chat prompts."""

    problem_chunks: list[RetrievedChunk]
    expert_chunks: list[RetrievedChunk]


@dataclass
class _IndexedChunk:
    chunk: DocumentChunk
    tf: Counter[str]
    norm: float
    embedding: list[float] = field(default_factory=list)


_framework_index: list[_IndexedChunk] = []
_collection_index: list[_IndexedChunk] = []
_framework_embedding_ready: bool = False
_collection_embedding_ready: bool = False

# Backward compatibility for tests that reference the framework index directly.
_index = _framework_index
_embedding_index_ready = False


def clear_index() -> None:
    """Clear all in-memory indices (used by tests and re-ingest)."""
    global _framework_embedding_ready, _collection_embedding_ready, _embedding_index_ready
    _framework_index.clear()
    _collection_index.clear()
    _framework_embedding_ready = False
    _collection_embedding_ready = False
    _embedding_index_ready = False


def _target_index(corpus: CorpusKind) -> list[_IndexedChunk]:
    return _collection_index if corpus == "collection" else _framework_index


def _embedding_ready(corpus: CorpusKind) -> bool:
    return _collection_embedding_ready if corpus == "collection" else _framework_embedding_ready


def _set_embedding_ready(corpus: CorpusKind, ready: bool) -> None:
    global _framework_embedding_ready, _collection_embedding_ready, _embedding_index_ready
    if corpus == "collection":
        _collection_embedding_ready = ready
    else:
        _framework_embedding_ready = ready
        _embedding_index_ready = ready


def index_chunks(
    chunks: Iterable[DocumentChunk],
    *,
    reset: bool = False,
    embed: bool = False,
    cache_path: str | None = None,
    corpus: CorpusKind | None = None,
) -> int:
    """Index document chunks into the framework or collection index."""
    chunk_list = list(chunks)
    if not chunk_list:
        if reset and corpus:
            _target_index(corpus).clear()
            _set_embedding_ready(corpus, False)
        return 0

    resolved_corpus: CorpusKind = corpus or chunk_list[0].corpus
    target = _target_index(resolved_corpus)
    if reset:
        target.clear()
        _set_embedding_ready(resolved_corpus, False)

    cache: dict[str, list[float]] = {}
    if embed and cache_path:
        cache = _load_cache(cache_path)

    profile = embed_profile_for_corpus(resolved_corpus)
    provider = get_embed_provider(profile) if embed else None
    newly_embedded: dict[str, list[float]] = {}
    added = 0

    for chunk in chunk_list:
        tokens = _tokenize(chunk.text)
        if not tokens:
            continue
        tf = Counter(tokens)
        norm = math.sqrt(sum(value * value for value in tf.values()))
        embedding: list[float] = []

        if embed and provider is not None:
            cache_key = _cache_key(chunk)
            if cache_key in cache:
                embedding = cache[cache_key]
            else:
                try:
                    vectors = provider.embed_passages([chunk.text])
                    embedding = vectors[0] if vectors else []
                    if embedding:
                        newly_embedded[cache_key] = embedding
                except Exception as exc:
                    logger.warning("embed failed for chunk %s: %s", chunk.chunk_id, exc)

        target.append(_IndexedChunk(chunk=chunk, tf=tf, norm=norm, embedding=embedding))
        added += 1

    if embed:
        has_any = any(item.embedding for item in target)
        _set_embedding_ready(resolved_corpus, has_any)
        if cache_path:
            if reset:
                cache = {
                    _cache_key(item.chunk): item.embedding
                    for item in target
                    if item.embedding
                }
                _save_cache(cache_path, cache)
            elif newly_embedded:
                cache.update(newly_embedded)
                _save_cache(cache_path, cache)

    return added


def ingest_and_index_directory(
    docs_dir: str,
    *,
    chunk_size: int,
    chunk_overlap: int,
    embed: bool = False,
    cache_path: str | None = None,
) -> tuple[int, int]:
    """Chunk all supported docs in a single directory and index them."""
    chunks = ingest_documents_from_dir(
        docs_dir,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    docs_count = len({chunk.source_path for chunk in chunks})
    chunks_count = index_chunks(
        chunks,
        reset=True,
        embed=embed,
        cache_path=cache_path,
        corpus="framework",
    )
    return docs_count, chunks_count


def ingest_and_index_knowledge(
    *,
    chunk_size: int,
    chunk_overlap: int,
    embed: bool = False,
    cache_path: str | None = None,
    include_collections: bool = True,
) -> tuple[int, int]:
    """Index starter/private knowledge and optional collection transcripts."""
    from app.core.knowledge_paths import knowledge_private_dir_if_exists, knowledge_starter_dir
    from app.knowledge.ingest import ingest_collection_chunks_from_disk
    from app.rag.ingest import ingest_documents_from_dirs

    starter_dir = str(knowledge_starter_dir())
    private_dir = knowledge_private_dir_if_exists()
    private_str = str(private_dir) if private_dir is not None else None

    framework_chunks = ingest_documents_from_dirs(
        starter_dir,
        private_str,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    collection_chunks: list[DocumentChunk] = []
    if include_collections:
        collection_chunks = ingest_collection_chunks_from_disk(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    docs_count = len({chunk.source_path for chunk in framework_chunks})
    docs_count += len({chunk.source_path for chunk in collection_chunks})

    index_chunks(
        framework_chunks,
        reset=True,
        embed=embed,
        cache_path=cache_path if embed else None,
        corpus="framework",
    )

    collection_embed = embed
    if include_collections and collection_chunks:
        if settings.rag_collection_embed_provider != settings.rag_embed_provider:
            from app.core.embeddings import probe_embed_model

            collection_embed = probe_embed_model(corpus="collection") or embed
        index_chunks(
            collection_chunks,
            reset=True,
            embed=collection_embed,
            cache_path=cache_path if collection_embed else None,
            corpus="collection",
        )

    chunks_count = len(_framework_index) + len(_collection_index)
    return docs_count, chunks_count


def retrieve(
    query: str,
    *,
    top_k: int = 3,
    min_score: float = 0.05,
    backend: Backend = "auto",
    retrieve_k: int | None = None,
) -> list[RetrievedChunk]:
    """Retrieve top chunks from the framework index (backward compatible)."""
    return _retrieve_from_indices(
        query,
        indices=["framework"],
        top_k=top_k,
        min_score=min_score,
        backend=backend,
        retrieve_k=retrieve_k,
    )


def retrieve_coach_context(query: str) -> CoachRetrievalResult:
    """Two-phase retrieval: situation alignment then expert solution expansion."""
    if not settings.rag_two_phase_enabled:
        chunks = retrieve(
            query,
            top_k=settings.rag_problem_top_k,
            min_score=settings.rag_min_score,
            backend=settings.rag_backend,  # type: ignore[arg-type]
        )
        return CoachRetrievalResult(problem_chunks=chunks, expert_chunks=[])

    problem_chunks = _retrieve_from_indices(
        query,
        indices=["framework", "collection"],
        top_k=settings.rag_problem_top_k,
        min_score=settings.rag_min_score,
        backend=settings.rag_backend,  # type: ignore[arg-type]
        retrieve_k=20,
        rerank_query=query,
    )

    solution_query = _build_solution_query(query, problem_chunks)
    expert_chunks = _retrieve_from_indices(
        solution_query,
        indices=["collection"],
        top_k=settings.rag_expert_top_k,
        min_score=settings.rag_min_score,
        backend=settings.rag_backend,  # type: ignore[arg-type]
        retrieve_k=30,
        chunk_roles={"solution", "general"},
        rerank_query=solution_query,
        dedup_key="collection",
    )
    expert_chunks = diversify_by_collection(
        expert_chunks,
        min_collections=settings.rag_min_collections,
        max_per_collection=settings.rag_max_chunks_per_collection,
    )
    return CoachRetrievalResult(
        problem_chunks=problem_chunks,
        expert_chunks=expert_chunks,
    )


def format_retrieval_context(chunks: list[RetrievedChunk]) -> str:
    """Format retrieved chunks for inclusion in a system prompt."""
    if not chunks:
        return ""

    lines = [
        "## Relevant Coaching Knowledge",
        (
            "Use ONLY the passages below to answer factual questions about "
            "coaching methods, frameworks, or techniques. "
            "If the answer is not contained in these passages, say you do not "
            "have that in your knowledge base and continue from general coaching "
            "principles — never invent sources, studies, statistics, or quotes."
        ),
        "",
    ]
    for index, chunk in enumerate(chunks, start=1):
        source_name = os.path.basename(chunk.source_path)
        lines.append(f"[{index}] Source: {source_name} (score={chunk.score:.2f})")
        lines.append(chunk.text)
        lines.append("")
    return "\n".join(lines).strip()


def format_coach_retrieval_context(result: CoachRetrievalResult) -> str:
    """Format two-phase retrieval for chat system prompts."""
    if not result.problem_chunks and not result.expert_chunks:
        return ""

    sections: list[str] = []
    if result.problem_chunks:
        lines = [
            "## Relevant Coaching Knowledge (situation)",
            (
                "Use these passages to understand the coaching situation. "
                "Do not invent facts beyond what is written here."
            ),
            "",
        ]
        for index, chunk in enumerate(result.problem_chunks, start=1):
            lines.append(_format_chunk_citation(index, chunk))
            lines.append(chunk.text)
            lines.append("")
        sections.append("\n".join(lines).strip())

    if result.expert_chunks:
        lines = [
            "## Expert Perspectives (stored solutions)",
            (
                "Present each expert separately. Compare where they agree or differ. "
                "Do not merge into one anonymous voice. "
                "Structure your reply as: (1) brief coaching suggestion, "
                "(2) what each expert recommends with attribution, "
                "(3) comparison when relevant."
            ),
            "",
        ]
        for chunk in result.expert_chunks:
            header = _format_expert_header(chunk)
            lines.append(header)
            lines.append(chunk.text)
            lines.append("")
        sections.append("\n".join(lines).strip())

    return "\n\n".join(sections)


def diversify_by_collection(
    chunks: list[RetrievedChunk],
    *,
    min_collections: int = 2,
    max_per_collection: int = 2,
    score_margin: float = 0.15,
) -> list[RetrievedChunk]:
    """Ensure multiple collections are represented in expert results."""
    if not chunks:
        return []

    top_score = chunks[0].score
    selected: list[RetrievedChunk] = []
    per_collection: Counter[str] = Counter()
    seen_collections: set[str] = set()

    for chunk in chunks:
        collection_key = chunk.collection_id or chunk.person_name or chunk.source_path
        if per_collection[collection_key] >= max_per_collection:
            continue
        if chunk.score < top_score - score_margin and len(seen_collections) >= min_collections:
            continue
        selected.append(chunk)
        per_collection[collection_key] += 1
        seen_collections.add(collection_key)

    if len(seen_collections) < min_collections:
        for chunk in chunks:
            collection_key = chunk.collection_id or chunk.person_name or chunk.source_path
            if collection_key in seen_collections:
                continue
            if per_collection[collection_key] >= max_per_collection:
                continue
            selected.append(chunk)
            per_collection[collection_key] += 1
            seen_collections.add(collection_key)
            if len(seen_collections) >= min_collections:
                break

    return selected


def _retrieve_from_indices(
    query: str,
    *,
    indices: list[IndexName],
    top_k: int,
    min_score: float,
    backend: Backend,
    retrieve_k: int | None = None,
    chunk_roles: set[str] | None = None,
    rerank_query: str | None = None,
    dedup_key: Literal["source", "collection"] = "source",
) -> list[RetrievedChunk]:
    if not any(_target_index(name) for name in indices):
        return []

    from app.core.scope import is_off_topic

    if is_off_topic(query):
        log_step(logger, "rag", "empty", level=logging.DEBUG, reason="off_topic")
        return []

    candidate_k = retrieve_k if retrieve_k is not None else settings.rag_retrieve_k
    candidate_k = max(candidate_k, top_k)

    ranked_lists: list[list[RetrievedChunk]] = []
    for index_name in indices:
        use_embedding = _resolve_backend(backend, index_name)
        hits = _stage1_candidates(
            query,
            index_name=index_name,
            top_k=candidate_k,
            min_score=min_score,
            use_embedding=use_embedding,
            chunk_roles=chunk_roles,
        )
        if hits:
            ranked_lists.append(hits)

    if not ranked_lists:
        return []

    if len(ranked_lists) == 1:
        candidates = ranked_lists[0]
    else:
        candidates = _reciprocal_rank_fusion(ranked_lists)[:candidate_k]

    rerank_applied = False
    effective_query = rerank_query or query
    if settings.rag_rerank_enabled and len(candidates) > top_k:
        try:
            from app.rag.reranker import rerank

            candidates = rerank(effective_query, candidates, top_k=top_k)
            rerank_applied = True
        except Exception as exc:
            log_step(logger, "rag.rerank", "fail", level=logging.WARNING, exc=type(exc).__name__)
            candidates = candidates[:top_k]
    else:
        candidates = candidates[:top_k]

    seen: set[str] = set()
    deduped: list[RetrievedChunk] = []
    for chunk in candidates:
        key = _dedup_key(chunk, mode=dedup_key)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(chunk)

    final_min = settings.rag_rerank_min_score if rerank_applied else min_score
    return [chunk for chunk in deduped if chunk.score >= final_min][:top_k]


def _dedup_key(chunk: RetrievedChunk, *, mode: str) -> str:
    if mode == "collection":
        return f"{chunk.collection_id or ''}:{chunk.source_path}"
    return chunk.source_path


def _build_solution_query(query: str, problem_chunks: list[RetrievedChunk]) -> str:
    snippets: list[str] = [query.strip()]
    for chunk in problem_chunks[:2]:
        snippet = " ".join(chunk.text.split()[:40])
        if snippet:
            snippets.append(snippet)
    topic = " ".join(snippets)
    return f"practical coaching solutions and approaches for: {topic}"


def _format_chunk_citation(index: int, chunk: RetrievedChunk) -> str:
    source_name = os.path.basename(chunk.source_path)
    if chunk.person_name and chunk.source_title:
        from app.rag.transcript import format_timestamp

        ts = ""
        if chunk.start_sec is not None and chunk.end_sec is not None:
            ts = f" ({format_timestamp(chunk.start_sec)}–{format_timestamp(chunk.end_sec)})"
        return (
            f"[{index}] Expert: {chunk.person_name} — "
            f"\"{chunk.source_title}\"{ts} (score={chunk.score:.2f})"
        )
    return f"[{index}] Source: {source_name} (score={chunk.score:.2f})"


def _format_expert_header(chunk: RetrievedChunk) -> str:
    from app.rag.transcript import format_timestamp

    person = chunk.person_name or "Expert"
    title = chunk.source_title or os.path.basename(chunk.source_path)
    ts = ""
    if chunk.start_sec is not None and chunk.end_sec is not None:
        ts = f" ({format_timestamp(chunk.start_sec)}–{format_timestamp(chunk.end_sec)})"
    return f"### {person} — \"{title}\"{ts}"


def _stage1_candidates(
    query: str,
    *,
    index_name: IndexName,
    top_k: int,
    min_score: float,
    use_embedding: bool,
    chunk_roles: set[str] | None,
) -> list[RetrievedChunk]:
    if (
        use_embedding
        and settings.rag_hybrid_rrf_enabled
        and _embedding_ready(index_name)
    ):
        embedding_hits = _retrieve_embedding(
            query,
            index_name=index_name,
            top_k=top_k,
            min_score=min_score,
            chunk_roles=chunk_roles,
        )
        token_hits = _retrieve_token(
            query,
            index_name=index_name,
            top_k=top_k,
            min_score=min_score,
            chunk_roles=chunk_roles,
        )
        if embedding_hits and token_hits:
            return _reciprocal_rank_fusion([embedding_hits, token_hits])[:top_k]
        if embedding_hits:
            return embedding_hits
        return token_hits

    if use_embedding:
        return _retrieve_embedding(
            query,
            index_name=index_name,
            top_k=top_k,
            min_score=min_score,
            chunk_roles=chunk_roles,
        )
    return _retrieve_token(
        query,
        index_name=index_name,
        top_k=top_k,
        min_score=min_score,
        chunk_roles=chunk_roles,
    )


def _reciprocal_rank_fusion(
    ranked_lists: list[list[RetrievedChunk]],
    *,
    k: int = 60,
) -> list[RetrievedChunk]:
    fused_scores: dict[str, float] = {}
    best_chunk: dict[str, RetrievedChunk] = {}

    for ranked in ranked_lists:
        for rank, chunk in enumerate(ranked, start=1):
            fused_scores[chunk.chunk_id] = fused_scores.get(chunk.chunk_id, 0.0) + (
                1.0 / (k + rank)
            )
            if (
                chunk.chunk_id not in best_chunk
                or chunk.score > best_chunk[chunk.chunk_id].score
            ):
                best_chunk[chunk.chunk_id] = chunk

    ordered = sorted(fused_scores.items(), key=lambda item: item[1], reverse=True)
    return [
        replace(best_chunk[chunk_id], score=score)
        for chunk_id, score in ordered
    ]


def _resolve_backend(backend: Backend, index_name: IndexName) -> bool:
    if backend == "embedding":
        return _embedding_ready(index_name)
    if backend == "token":
        return False
    return _embedding_ready(index_name)


def _retrieve_embedding(
    query: str,
    *,
    index_name: IndexName,
    top_k: int,
    min_score: float,
    chunk_roles: set[str] | None,
) -> list[RetrievedChunk]:
    try:
        from app.core.embeddings import cosine_similarity, embed_query

        corpus: CorpusKind = index_name
        query_vec = embed_query(query, corpus=corpus)
    except Exception as exc:
        logger.warning("rag: embedding query failed (%s), falling back to token", exc)
        return _retrieve_token(
            query,
            index_name=index_name,
            top_k=top_k,
            min_score=min_score,
            chunk_roles=chunk_roles,
        )

    scored: list[RetrievedChunk] = []
    for indexed in _target_index(index_name):
        if not indexed.embedding:
            continue
        if chunk_roles and indexed.chunk.chunk_role not in chunk_roles:
            continue
        score = cosine_similarity(query_vec, indexed.embedding)
        if score < min_score:
            continue
        scored.append(_to_retrieved_chunk(indexed, score))

    scored.sort(key=lambda item: item.score, reverse=True)
    return scored[:top_k]


def _retrieve_token(
    query: str,
    *,
    index_name: IndexName,
    top_k: int,
    min_score: float,
    chunk_roles: set[str] | None,
) -> list[RetrievedChunk]:
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    query_tf = Counter(query_tokens)
    query_norm = math.sqrt(sum(value * value for value in query_tf.values()))
    if query_norm == 0.0:
        return []

    scored: list[RetrievedChunk] = []
    for indexed in _target_index(index_name):
        if chunk_roles and indexed.chunk.chunk_role not in chunk_roles:
            continue
        score = _tf_cosine(query_tf, query_norm, indexed.tf, indexed.norm)
        if score < min_score:
            continue
        scored.append(_to_retrieved_chunk(indexed, score))

    scored.sort(key=lambda item: item.score, reverse=True)
    return scored[:top_k]


def _to_retrieved_chunk(indexed: _IndexedChunk, score: float) -> RetrievedChunk:
    chunk = indexed.chunk
    return RetrievedChunk(
        chunk_id=chunk.chunk_id,
        source_path=chunk.source_path,
        text=chunk.text,
        score=score,
        collection_id=chunk.collection_id,
        person_name=chunk.person_name,
        source_title=chunk.source_title,
        start_sec=chunk.start_sec,
        end_sec=chunk.end_sec,
        chunk_role=chunk.chunk_role,
        corpus=chunk.corpus,
    )


def _cache_key(chunk: DocumentChunk) -> str:
    text_hash = hashlib.sha256(chunk.text.encode()).hexdigest()[:16]
    return f"{chunk.embed_profile_id}::{chunk.chunk_id}::{text_hash}"


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
    return [match.group(0).lower() for match in _TOKEN_RE.finditer(text)]
