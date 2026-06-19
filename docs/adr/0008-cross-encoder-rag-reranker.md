# ADR-0008: Cross-Encoder Reranker for Two-Stage RAG Retrieval

**Date:** 2026-06-12
**Status:** Accepted (implementation updated 2026-06-14 — reranker moved to local fastembed)

> **Update (2026-06-13):** Stage-2 reranking initially ran through Ollama
> (`dengcao/bge-reranker-v2-m3`) via `app/core/rerank.py`.
>
> **Update (2026-06-14):** Ollama cannot serve cross-encoder reranker models
> (llama.cpp crashes with `GGML_ASSERT(n_outputs_max …)`; ollama/ollama #3368).
> Stage-2 reranking now runs **in-process** via fastembed + ONNX
> (`BAAI/bge-reranker-base`). The two-stage retrieval design is unchanged.

> **Update (2026-06-19):** Defaults tuned for anti-hallucination — `RAG_RETRIEVE_K=30`,
> `RAG_TOP_K=2`, `RAG_RERANK_MIN_SCORE=0.42`, hybrid RRF enabled. Historical ADR text
> below references the original `top_k=3` / `RAG_RETRIEVE_K=25` values at acceptance time.

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
   `fastembed.rerank.cross_encoder.TextCrossEncoder` (ONNX, no PyTorch) and
   return the best `RAG_TOP_K` (unchanged at 3).  Falls back to stage-1 ordering
   when fastembed is not installed or the model cannot be loaded.

The cross-encoder is wrapped in `app/core/rerank.py` (core singleton + scoring)
and `app/rag/reranker.py` (thin pipeline adapter) following the pattern of
`app/core/embeddings.py`: a module-level singleton protected by a threading lock,
a `probe_rerank_model()` function called as a background task at startup, batch
scoring with configurable batch size and passage truncation, and silent fallback on
any import or runtime error.  Raw logits are passed through a sigmoid so rerank
scores remain in `(0, 1)` and stay compatible with `rag_min_score`.

The chosen default model is `BAAI/bge-reranker-base` (via fastembed):
- Runs entirely in-process with ONNX Runtime — no Ollama, no PyTorch, no GPU required.
- ~1 GB download cached under `RAG_RERANK_CACHE_DIR` (default
  `<project_root>/data/rerank_cache`; absolute `/app/data/rerank_cache` in Docker).
- Corrupt/incomplete HuggingFace blobs are detected and purged before load so a
  failed first download does not leave the cache in a broken state permanently.
- Multilingual support covers varied coaching phrasing.

A **per-source deduplication** step is applied after reranking: only the
highest-scoring chunk per `source_path` is kept before the `top_k` cut.  This
prevents overlapping 512-token windows from the same document from flooding the
context window.

## Consequences

**Positive:**
- Recall improves because stage-1 can now retrieve 25 candidates instead of
  committing to 3 with a coarser scorer.
- Precision improves because the cross-encoder can distinguish near-duplicate
  candidates that the bi-encoder scores identically.
- Multilingual queries are handled correctly by `bge-reranker-base`.
- Fully opt-in: `RAG_RERANK_ENABLED=false` (or fastembed absent) silently
  reverts to the original single-stage behaviour — no request failures, no
  configuration changes required for existing deployments.
- No changes required at any call site (`chat.py`, `briefing.py`,
  `openai_compat.py`) — the improvement is transparent behind `retrieve()`.
- No PyTorch dependency: fastembed uses ONNX Runtime only — Docker image stays
  ~18 MB heavier, not gigabytes.
- CI remains dependency-free: all reranker tests mock `TextCrossEncoder`.

**Negative:**
- Cross-encoder adds ~50–200 ms of synchronous latency on CPU for 25 candidates.
  This is acceptable given the quality-first goal but may be noticeable on
  very constrained hardware.
- First request (or startup probe) triggers a model download (~1 GB) from
  HuggingFace if the model is not cached.  The cache survives Docker
  restarts/rebuilds via the `coach-assistant-data` named volume.
- `bge-reranker-base` is smaller and less multilingual than the originally
  planned `bge-reranker-v2-m3`, which is not yet available in fastembed's
  supported model list.

## Alternatives Considered

| Option | Reason Not Chosen |
|--------|------------------|
| Ollama LLM pointwise rerank (prompt-based) | Higher latency and token cost; inconsistent score calibration |
| Hybrid RRF (embedding + token merge) before rerank | Adds recall but also complexity; deferred to v2 — start with single-backend widening |
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | English-only; weaker on non-English coaching input |
| `jina-reranker-v2-base-multilingual` | Strong quality but heavier; `bge-reranker-base` is already available in fastembed and sufficient for v1 |
| `bge-reranker-v2-m3` via sentence-transformers | Requires PyTorch (+1–2 GB); not yet in fastembed's supported models list |
| Reranker as a separate Docker service | Unnecessary RPC overhead at single-app scale; keep in-process for simplicity |
| Cached rerank scores | Query-dependent; short corpus means latency is acceptable without a cache in v1 |

## Future Direction

- **Hybrid RRF (v2)**: run embedding + token backends in parallel, merge top ~30 via
  Reciprocal Rank Fusion, then rerank.  Improves recall for queries containing exact
  framework names (GROW, MI) that the bi-encoder under-weights.
- **Async rerank**: ~~wrap the synchronous `rerank()` call in `asyncio.to_thread()`~~ —
  done: `build_system_prompt()` in `chat.py` and `_build_briefing_context()` in
  `briefing.py` both run inside `asyncio.to_thread()` so the event loop is not blocked.
- **ANN index**: when the corpus exceeds ~5 000–10 000 chunks, replace the brute-force
  cosine scan with an ANN index (e.g. `hnswlib`).  The `retrieve()` interface is stable.
- **bge-reranker-v2-m3 upgrade**: once fastembed ships ONNX support for the v2-m3 model,
  upgrade from `bge-reranker-base` to restore full multilingual performance.
