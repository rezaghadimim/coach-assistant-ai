# RAG Pipeline

## Purpose

RAG is the system's **knowledge layer** — it stores what the model knows, not how it behaves.

Use RAG for any content that:
- May change or grow over time
- Is too large to fit in a prompt or model weights
- Requires accurate, traceable retrieval (books, articles, documentation, manuals)

For behavior (coaching tone, style, questioning strategy), see [`FINETUNE.md`](FINETUNE.md).

## What is implemented

- Local ingestion of `.txt`, `.md`, and `.pdf` documents (`app/rag/ingest.py`)
- Two-stage in-memory retrieval index (`app/rag/retriever.py`):
  - **Stage 1** — bi-encoder cosine (E5-small via Ollama) or TF cosine fallback; retrieves a wider candidate pool (`RAG_RETRIEVE_K`, default 25)
  - **Stage 2** — optional local cross-encoder reranker (`app/core/rerank.py` + `app/rag/reranker.py`) narrows pool to final `RAG_TOP_K` (default 3)
- Source-level deduplication: only the highest-scoring chunk per source file reaches context
- API endpoint to reindex documents (`POST /api/ingest`)
- Chat integration that injects retrieved chunks into system prompt

## Retrieval pipeline

```
Query
  → Stage 1: E5 embed / TF cosine  (retrieve_k=25 candidates, min_score≥0.15)
  → Stage 2: fastembed reranker    (optional, narrows to top_k=3)
  → source deduplication
  → format_retrieval_context()     (adds grounding contract + source tags)
  → build_system_prompt()
  → LLM
```

## Grounding contract

Every context window that contains retrieved chunks is prepended with a strict instruction:

> **Use ONLY the passages below to answer factual questions about coaching methods, frameworks, or techniques. If the answer is not contained in these passages, say you do not have that in your knowledge base and continue from general coaching principles — never invent sources, studies, statistics, or quotes.**

This prevents the LLM from hallucinating "facts" when retrieved chunks are marginally relevant.  Each chunk is also tagged with its `source_path` filename so the model can attribute answers rather than fabricate citations.

When no chunk clears the `RAG_MIN_SCORE` floor (default `0.15`), **no context is injected at all** — avoiding the negative priming effect where low-score chunks suggest plausible-sounding but wrong content.

This follows the *retrieval-conditional abstain* pattern: inject context only when the retriever is confident, and let the model abstain gracefully when it is not.

## Ingestion

```bash
python scripts/ingest.py --docs-dir ./docs/knowledge/
```

`docs/knowledge/` is treated as a local-only ingest directory. Add your real source
documents there on your machine or in a mounted volume; the repo only tracks a sample file.

Or via API:

```bash
curl -X POST http://localhost:8000/api/ingest \
  -H "Content-Type: application/json" \
  -d '{"chunk_size":512,"chunk_overlap":50}'
```

## Reranker setup

Stage-2 reranking runs **locally in the API process** via [fastembed](https://github.com/qdrant/fastembed) (ONNX + onnxruntime). No Ollama, no PyTorch.

Default model: `BAAI/bge-reranker-base` (~1 GB). It is downloaded automatically on first use and cached under `RAG_RERANK_CACHE_DIR` (default `data/rerank_cache`).

Ollama cannot serve cross-encoder reranker models (they crash llama.cpp with `GGML_ASSERT(n_outputs_max …)`; see [ollama/ollama#3368](https://github.com/ollama/ollama/issues/3368)), so reranking is not done through Ollama.

When fastembed is missing or the model fails to load, the pipeline falls back to stage-1 ordering — no configuration change required.

### Key environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RAG_RETRIEVE_K` | `25` | Stage-1 candidate pool size |
| `RAG_MIN_SCORE` | `0.15` | Minimum score to include a chunk; 0 means inject everything |
| `RAG_RERANK_ENABLED` | `true` | Enable/disable reranking |
| `RAG_RERANK_MODEL` | `BAAI/bge-reranker-base` | fastembed cross-encoder model name |
| `RAG_RERANK_BATCH_SIZE` | `32` | Passages scored per ONNX batch |
| `RAG_RERANK_MAX_PASSAGE_CHARS` | `2000` | Passage truncation before scoring |
| `RAG_RERANK_CACHE_DIR` | `<project_root>/data/rerank_cache` | On-disk model cache (absolute by default) |
| `RAG_TOP_K` | `3` | Final number of chunks injected into prompt |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama URL for **embeddings only** (stage 1) |

`OLLAMA_RERANK_MODEL` is still accepted as a legacy alias for `RAG_RERANK_MODEL`.

Reranker availability is reported in the `/health` endpoint under the `rerank` key.
While the background warmup is in progress, `/health` returns `"status": "warming"` for
the `rerank` key — the endpoint itself is never blocked by the model download.

### Cache persistence

The model is cached under `RAG_RERANK_CACHE_DIR` and survives normal restarts:

| Action | Cache preserved? |
|--------|-----------------|
| `docker compose restart` | Yes |
| `docker compose down` then `up` (no `-v`) | Yes |
| `docker compose up --build` | Yes — volumes are independent of image layers |
| `docker compose down -v` | **No** — wipes the entire named volume |

**Manual warm-up** — run once on a stable network to pre-populate the cache so
subsequent boots don't download:

```bash
# Local dev
python -c "from app.core.rerank import probe_rerank_model; print('rerank_ready=', probe_rerank_model())"

# Docker
docker compose exec coach-api python -c "from app.core.rerank import probe_rerank_model; print('rerank_ready=', probe_rerank_model())"

# Verify the cache exists
docker compose exec coach-api ls -lah /app/data/rerank_cache
```

If a download is interrupted (`.incomplete` blobs appear), the application
auto-purges the partial cache and re-downloads on next startup — just ensure the
container is not restarted mid-download.

## Testing

```bash
python3 -m unittest discover -s tests -p "test_*.py"
```

- `tests/test_rerank.py` — unit tests with a mocked encoder (fast, offline)
- `tests/test_rag_rerank.py` — two-stage `retrieve()` pipeline tests (mocked reranker)
- `tests/test_rerank_integration.py` — optional end-to-end test against the real ONNX model (skipped when the model is not cached; set `RUN_RERANK_INTEGRATION=1` to download and run)

## Grounding eval

`scripts/eval_rag_grounding.py` evaluates two retrieval-quality properties:

1. **Abstention** — off-topic queries (weather, code, math, recipes …) should return zero chunks above `RAG_MIN_SCORE`.  If chunks leak through, the LLM is primed to hallucinate answers to out-of-domain questions.
2. **Recall** — in-corpus coaching questions should return at least one chunk; optional keyword checks verify topic coverage.

```bash
# Run with default token backend (offline, no Ollama needed)
PYTHONPATH=. python scripts/eval_rag_grounding.py --show-failures

# Run with embedding backend
PYTHONPATH=. python scripts/eval_rag_grounding.py --backend embedding --show-failures

# Fail if accuracy < 85%
PYTHONPATH=. python scripts/eval_rag_grounding.py --min-accuracy 0.85 --exit-nonzero
```

Eval cases live in `data/eval/rag_grounding.jsonl`.  Add rows to extend coverage:

```json
{"question": "off-topic query here", "must_abstain": true, "category": "off_topic"}
{"question": "What is the GROW model?", "must_abstain": false, "keywords": ["GROW", "Goal"], "category": "coaching_concept"}
```
