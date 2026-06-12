# ADR-0008: Cross-Encoder Reranker for Two-Stage RAG Retrieval

**Date:** 2026-06-12
**Status:** Accepted

## Context

The RAG pipeline (ADR-0003) originally retrieved `top_k=3` chunks using a single
bi-encoder pass: either dense cosine similarity (E5-small via Ollama) or sparse TF
cosine.  This "retrieve-once-and-done" design has two compounding problems:

1. **Recall ceiling** — with `top_k=3` the stage-1 scorer must be both precise and
   exhaustive; any relevant chunk outside the top 3 is permanently lost.
2. **Bi-encoder coarseness** — E5-small encodes query and passage independently.
   It is fast but cannot compare a specific query against a specific passage in
   context; subtle relevance differences between candidates are missed.

Cross-encoders jointly encode the (query, passage) pair and consistently produce
stronger relevance signals than bi-encoders, at the cost of higher latency.  The
standard production pattern is: **widen recall with a fast bi-encoder, then
re-score a narrow candidate pool with a cross-encoder**.

The system already has an optional dependency pattern (`finetune` group in
`pyproject.toml`) and a graceful probe/fallback convention (`probe_embed_model()`
in `app/core/embeddings.py`), so the reranker can follow the same design.

## Decision

Add an **optional two-stage retrieval pipeline** to `app/rag/retriever.py`:

1. **Stage 1** — fetch up to `RAG_RETRIEVE_K` (default 25) candidates using the
   existing bi-encoder or TF cosine backend.
2. **Stage 2** — score all candidates as `(query, passage)` pairs using
   `sentence_transformers.CrossEncoder` and return the best `RAG_TOP_K` (unchanged
   at 3).  Falls back to stage-1 ordering when the package is not installed.

The cross-encoder is wrapped in `app/rag/reranker.py` following the pattern of
`app/core/embeddings.py`: a module-level singleton, a `probe_rerank_model()`
function called at startup, batch scoring with configurable batch size and passage
truncation, and silent fallback on any import or runtime error.

The chosen default model is `BAAI/bge-reranker-v2-m3`:
- Multilingual — aligns with `karuniaperjuangan/multilingual-e5-small` used in
  tool routing, covering the Farsi/English coaching use case.
- Strong MTEB reranking scores with a reasonable ~568M-parameter size.
- Available via HuggingFace `sentence-transformers` with no extra runtime.

A **per-source deduplication** step is applied after reranking: only the
highest-scoring chunk per `source_path` is kept before the `top_k` cut.  This
prevents overlapping 512-token windows from the same document from flooding the
context window.

The `sentence-transformers` package is placed in an optional dependency group
(`rag-rerank`) in `pyproject.toml`, mirroring the existing `finetune` group.  It
is not added to `requirements.txt` or the `Dockerfile`, keeping the slim
deployment image unchanged.

## Consequences

**Positive:**
- Recall improves because stage-1 can now retrieve 25 candidates instead of
  committing to 3 with a coarser scorer.
- Precision improves because the cross-encoder can distinguish near-duplicate
  candidates that the bi-encoder scores identically.
- Multilingual queries (Farsi/English) are handled correctly by `bge-reranker-v2-m3`.
- Fully opt-in: `RAG_RERANK_ENABLED=false` (or the package absent) silently
  reverts to the original single-stage behaviour — no request failures, no
  configuration changes required for existing deployments.
- No changes required at any call site (`chat.py`, `briefing.py`,
  `openai_compat.py`) — the improvement is transparent behind `retrieve()`.
- CI remains dependency-free: all reranker tests mock `CrossEncoder`.

**Negative:**
- Cross-encoder adds ~50–200 ms of synchronous latency on CPU for 25 candidates.
  This is acceptable given the quality-first goal but may be noticeable on
  very constrained hardware.
- First request (or startup probe) triggers a model download (~1–2 GB) from
  HuggingFace if the model is not cached.
- `sentence-transformers` pulls in PyTorch, which is a large transitive
  dependency.  Docker images that opt in will grow significantly.

## Alternatives Considered

| Option | Reason Not Chosen |
|--------|------------------|
| Ollama LLM pointwise rerank (prompt-based) | Higher latency and token cost; inconsistent score calibration |
| Hybrid RRF (embedding + token merge) before rerank | Adds recall but also complexity; deferred to v2 — start with single-backend widening |
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | English-only; misses Farsi coaching input |
| `jina-reranker-v2-base-multilingual` | Strong quality but heavier; `bge-reranker-v2-m3` covers the same multilingual use case |
| Cached rerank scores | Query-dependent; short corpus means latency is acceptable without a cache in v1 |

## Future Direction

- **Hybrid RRF (v2)**: run embedding + token backends in parallel, merge top ~30 via
  Reciprocal Rank Fusion, then rerank.  Improves recall for queries containing exact
  framework names (GROW, MI) that the bi-encoder under-weights.
- **Async rerank**: wrap the synchronous `rerank()` call in `asyncio.to_thread()` to
  avoid blocking the FastAPI event loop.
- **ANN index**: when the corpus exceeds ~5 000–10 000 chunks, replace the brute-force
  cosine scan with an ANN index (e.g. `hnswlib`).  The `retrieve()` interface is stable.
