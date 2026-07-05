# ADR-0003: In-Memory Token-Similarity RAG Retrieval

**Date:** 2024-01-01
**Status:** Accepted (extended by ADR-0008, ADR-0011 — see below)

> **Update (2026-06-25):** ADR-0011 extends this decision with dual in-memory indices
> (`framework_index` + `collection_index`), pluggable embedding providers (Ollama /
> OpenRouter / OpenAI), per-person video/transcript collections, and two-phase coach
> retrieval (`retrieve_coach_context()`). The core in-memory design and stable
> `retrieve()` interface are unchanged. See [ADR-0011](0011-collection-video-knowledge.md).

> **Update (2026-06):** Stage-1 retrieval now uses Ollama E5 embeddings with TF cosine
> fallback and optional hybrid RRF; stage-2 uses a local fastembed cross-encoder
> (ADR-0008). The original TF-only description below reflects the initial MVP.

## Context

Phase 2 requires a Retrieval-Augmented Generation (RAG) layer so the coaching assistant can ground its responses in user-supplied documents (books, articles, frameworks). The system must:

- Retrieve relevant chunks from a local document corpus at query time.
- Require no external services or databases.
- Be simple to set up and reason about.
- Be replaceable with a more powerful solution in the future.

## Decision

Implement an **in-memory, token-frequency (TF) cosine-similarity index** (`app/rag/retriever.py`). Documents are chunked, tokenised, and stored as sparse term-frequency vectors in a Python dict. At query time the query vector is compared to all stored vectors using cosine similarity and the top-k chunks are returned.

> **Note (current state):** The MVP description below reflects the original TF-only
> design. As of the updates above, TF cosine is now the **fallback** backend behind
> Ollama E5 embeddings + a cross-encoder reranker (ADR-0008), and embeddings are
> cached on disk per corpus, so the "index is lost on restart" consequence no longer
> applies to the embedding path. The `retrieve()` interface is unchanged.

## Consequences

**Positive:**
- Zero additional dependencies — no vector database or embedding service required.
- Instant setup — the index is rebuilt in memory at application start or via `/api/ingest`.
- Fully deterministic and easy to test.
- Sufficient quality for a single-user local deployment with a small corpus.

**Negative:**
- Semantic similarity is not captured — only token overlap. Synonyms and paraphrases are missed.
- Does not scale beyond a few thousand chunks before query latency becomes noticeable.
- The index is lost on application restart (re-ingestion required).

## Alternatives Considered

| Option | Reason Not Chosen |
|--------|------------------|
| ChromaDB / Qdrant (vector store) | External service or disk dependency; overkill for MVP scope |
| Sentence-Transformers embeddings | Additional ~500 MB model download; higher complexity for Phase 2 MVP |
| SQLite FTS5 full-text search | Better than TF-IDF but still no semantic understanding; adds SQLite coupling to RAG |
| LlamaIndex / LangChain | Heavy framework abstractions; opaque to beginners; planned to keep code readable |

## Future Direction

When the corpus grows or semantic accuracy becomes critical, replace the in-memory index with a local vector store (e.g., ChromaDB) and an embedding model (e.g., `nomic-embed-text` via Ollama). The `retrieve()` interface is stable and the swap can be made without touching the chat API.
