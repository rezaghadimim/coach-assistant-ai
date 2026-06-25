# RAG Pipeline

## Purpose

RAG is the system's **knowledge layer** — it stores what the model knows, not how it behaves.

Use RAG for any content that:
- May change or grow over time
- Is too large to fit in a prompt or model weights
- Requires accurate, traceable retrieval (books, articles, documentation, manuals)

For behavior (coaching tone, style, questioning strategy), see [`FINETUNE.md`](FINETUNE.md).

## What is implemented

- Local ingestion of `.txt`, `.md`, and `.pdf` from **starter + private** knowledge dirs (`app/rag/ingest.py`, `app/core/knowledge_paths.py`)
- **Per-person video/transcript collections** under `data/knowledge/collections/` with SRT/VTT/txt/md support (`app/rag/transcript.py`, `app/knowledge/ingest.py`)
- Optional media jobs: local video/audio → Whisper (`app/knowledge/jobs.py`); YouTube URLs → yt-dlp captions or Whisper fallback
- **Dual in-memory indices** (`app/rag/retriever.py`): `framework_index` (starter + private) and `collection_index` (expert video knowledge)
- **Pluggable embedding providers** (`app/core/embed_providers/`): Ollama (default), OpenRouter, OpenAI — framework vs collection corpora can use different providers
- Heading-aware chunking for markdown (splits on `##` / `###` before fixed-size windows); time-aware chunking for transcripts
- Two-stage retrieval per phase (bi-encoder → cross-encoder rerank):
  - **Stage 1** — bi-encoder cosine (E5-small via Ollama, or cloud embed for collection index), TF cosine fallback, or **hybrid RRF** merge when `RAG_HYBRID_RRF_ENABLED=true`
  - **Stage 2** — optional local cross-encoder reranker (`app/core/rerank.py` + `app/rag/reranker.py`)
- **Two-phase coach retrieval** (`retrieve_coach_context()`): phase 1 aligns on the coaching situation; phase 2 expands expert solutions across collections with `diversify_by_collection()`
- Off-topic abstention: scope guard short-circuits retrieval before similarity search (`app/core/scope.py`)
- Source-level deduplication; collection-aware dedup key `(collection_id, source_path)` in phase 2
- Private overrides: same relative path in `private/` wins over `starter/`
- API: `POST /api/ingest` (framework + collections), `GET/POST /api/collections`, `POST /api/collections/{id}/reindex`, `POST /api/collections/process-jobs`
- Chat/briefing integration via `format_coach_retrieval_context()` — situation + per-expert solution sections

## Retrieval pipeline (coach chat)

When `RAG_TWO_PHASE_ENABLED=true` (default):

```
Coach message
  → off-topic check (scope guard)
  → Phase 1 — problem alignment
      → search framework_index + collection_index (RRF merge)
      → rerank with original query
      → top RAG_PROBLEM_TOP_K chunks (default 3)
  → Phase 2 — expert solutions
      → build solution query from phase-1 hits
      → search collection_index only
      → rerank → diversify_by_collection (min RAG_MIN_COLLECTIONS experts)
      → top RAG_EXPERT_TOP_K chunks (default 6)
  → format_coach_retrieval_context()
  → build_system_prompt()
  → LLM
```

Legacy single-index path (`retrieve()` on framework corpus only) remains for tests and simple callers.

### Single-corpus pipeline (framework-only)

```
Query
  → off-topic check (scope guard — abstain if out of domain)
  → Stage 1: E5 embed / TF cosine / hybrid RRF  (retrieve_k=30, min_score≥0.15)
  → Stage 2: fastembed reranker    (optional, narrows to top_k=2, floor≥0.42)
  → source deduplication
  → format_retrieval_context()     (adds grounding contract + source tags)
  → build_system_prompt()
  → LLM
```

## Grounding contract

Coach chat uses **two prompt sections** when two-phase retrieval is enabled:

1. **Relevant Coaching Knowledge (situation)** — frameworks and context for understanding the problem. Do not invent facts beyond these passages.
2. **Expert Perspectives (stored solutions)** — attributed solutions from stored video/transcript knowledge. Present each expert separately; note agreements and differences.

The LLM is instructed to structure replies as: brief coaching suggestion → per-expert recommendations (with guide title + timestamp) → comparison when relevant.

Every context window that contains retrieved chunks is also governed by a strict abstention rule:

> **Use ONLY the passages below to answer factual questions about coaching methods, frameworks, or techniques. If the answer is not contained in these passages, say you do not have that in your knowledge base and continue from general coaching principles — never invent sources, studies, statistics, or quotes.**

This prevents the LLM from hallucinating "facts" when retrieved chunks are marginally relevant. Framework chunks are tagged by filename; collection chunks include **expert name**, **guide title**, and **timestamp range** when available.

When no chunk clears the score floor, **no context is injected at all** — avoiding negative priming from low-score chunks.

Off-topic queries detected by the scope guard (`app/core/scope.py`) return zero chunks immediately.

This follows the *retrieval-conditional abstain* pattern: inject context only when the retriever is confident, and let the model abstain gracefully when it is not.

## Knowledge layout

```text
docs/knowledge/
├── README.md                    ← overview (this repo)
├── SETUP_PRIVATE_REPO.md        ← GitHub + clone guide (start here)
├── private-repo-scaffold/       ← reference files for new private repos
├── starter/                     ← committed bootstrap docs
└── private/                     ← git submodule → coach-knowledge
```

**Starter** docs live in this repo. **Real documents** live in the private
[`coach-knowledge`](https://github.com/rezaghadimim/coach-knowledge) repo, linked
as a submodule at `private/`. See
[`docs/knowledge/SETUP_PRIVATE_REPO.md`](knowledge/SETUP_PRIVATE_REPO.md).

On every ingest, starter files are indexed first, then private files are **appended**.
Same relative path in both → **private wins**.

### Expert video collections

Per-person guides (video transcripts, local media, YouTube) live under:

```text
data/knowledge/collections/
└── {slug}/
    ├── collection.json       # person_name, title, optional embed_provider override
    └── sources/
        └── {source-id}/
            ├── meta.json     # title, source_type, uri
            └── transcript.vtt   # or .srt / .txt / .md / video file
```

Metadata is mirrored in SQLite (`app/knowledge/store.py`). On startup and `POST /api/ingest`, framework docs and all collection transcripts are indexed into separate in-memory indices.

See [`docs/knowledge/README.md`](knowledge/README.md) for collection workflow.

## Ingestion

```bash
# After clone (once):
./scripts/setup_knowledge_private_repo.sh
# or: git submodule update --init --recursive docs/knowledge/private

python3 scripts/ingest.py
```

Or via API:

```bash
curl -X POST http://localhost:8000/api/ingest \
  -H "Content-Type: application/json" \
  -d '{"chunk_size": 300, "chunk_overlap": 50}'
```

Legacy single-directory ingest still works for tests:

```bash
python3 scripts/ingest.py --starter-dir ./my/docs --private-dir ./my/private
```

## Reranker setup

Stage-2 reranking runs **locally in the API process** via [fastembed](https://github.com/qdrant/fastembed) (ONNX + onnxruntime). No Ollama, no PyTorch.

Default model: `BAAI/bge-reranker-base` (~1 GB). It is downloaded automatically on first use and cached under `RAG_RERANK_CACHE_DIR` (default `data/rerank_cache`).

Ollama cannot serve cross-encoder reranker models (they crash llama.cpp with `GGML_ASSERT(n_outputs_max …)`; see [ollama/ollama#3368](https://github.com/ollama/ollama/issues/3368)), so reranking is not done through Ollama.

When fastembed is missing or the model fails to load, the pipeline falls back to stage-1 ordering — no configuration change required.

### Key environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RAG_MIN_SCORE` | `0.15` | Stage-1 candidate pool floor (bi-encoder / token cosine) |
| `RAG_RERANK_MIN_SCORE` | `0.42` | Final floor after cross-encoder reranking (sigmoid 0–1) |
| `RAG_HYBRID_RRF_ENABLED` | `true` | Merge embedding + token stage-1 lists via RRF before rerank |
| `RAG_RETRIEVE_K` | `30` | Stage-1 candidate pool size |
| `RAG_RERANK_ENABLED` | `true` | Enable/disable reranking |
| `RAG_RERANK_MODEL` | `BAAI/bge-reranker-base` | fastembed cross-encoder model name |
| `RAG_RERANK_BATCH_SIZE` | `32` | Passages scored per ONNX batch |
| `RAG_RERANK_MAX_PASSAGE_CHARS` | `2000` | Passage truncation before scoring |
| `RAG_RERANK_CACHE_DIR` | `<project_root>/data/rerank_cache` | On-disk model cache (absolute by default) |
| `RAG_KNOWLEDGE_STARTER_DIR` | `docs/knowledge/starter` | Committed bundled docs (legacy: `RAG_KNOWLEDGE_TEMPLATES_DIR`, `RAG_DOCS_DIR`) |
| `RAG_KNOWLEDGE_PRIVATE_DIR` | `docs/knowledge/private` | Private knowledge (git submodule → `coach-knowledge`) merged on ingest |
| `RAG_TOP_K` | `2` | Final chunks for legacy `retrieve()` (framework only) |
| `RAG_TWO_PHASE_ENABLED` | `true` | Enable two-phase coach retrieval in chat/briefing |
| `RAG_PROBLEM_TOP_K` | `3` | Phase-1 situation chunks |
| `RAG_EXPERT_TOP_K` | `6` | Phase-2 expert solution chunks |
| `RAG_MIN_COLLECTIONS` | `2` | Minimum distinct experts in phase 2 |
| `RAG_MAX_CHUNKS_PER_COLLECTION` | `2` | Cap per expert in phase 2 |
| `RAG_EMBED_PROVIDER` | `ollama` | Framework + query default: `ollama` \| `openrouter` \| `openai` |
| `RAG_EMBED_MODEL` | `karuniaperjuangan/multilingual-e5-small` | Model for framework corpus |
| `RAG_COLLECTION_EMBED_PROVIDER` | `openrouter` | Collection ingest: `openrouter` \| `openai` \| `ollama` |
| `RAG_COLLECTION_EMBED_MODEL` | `openai/text-embedding-3-small` | Model for collection corpus (batch at ingest) |
| `RAG_COLLECTIONS_DIR` | `data/knowledge/collections` | Filesystem root for per-person collections |
| `OPENAI_API_KEY` | *(empty)* | Required when `RAG_*_EMBED_PROVIDER=openai` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama URL for **embeddings** (stage 1) |

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
- `tests/test_rag_rrf.py` — hybrid RRF stage-1 merge tests
- `tests/test_transcript_parser.py` — SRT/VTT parsing and time-aware chunks
- `tests/test_collection_ingest.py` — filesystem collection discovery
- `tests/test_two_phase_retrieval.py` — `retrieve_coach_context()` and diversity
- `tests/test_embed_providers.py` — Ollama / OpenRouter / OpenAI factory
- `tests/test_knowledge_jobs.py` — media job error paths (offline-safe)
- `tests/test_rerank_integration.py` — optional end-to-end test against the real ONNX model (skipped when the model is not cached; set `RUN_RERANK_INTEGRATION=1` to download and run)

## Grounding eval

`scripts/eval_rag_grounding.py` evaluates two retrieval-quality properties:

1. **Abstention** — off-topic queries (weather, code, math, recipes …) should return zero chunks above `RAG_MIN_SCORE`.  If chunks leak through, the LLM is primed to hallucinate answers to out-of-domain questions.
2. **Recall** — in-corpus coaching questions should return at least one chunk; optional keyword checks verify topic coverage.

```bash
# Run with default token backend (offline, no Ollama needed)
PYTHONPATH=. python3 scripts/eval_rag_grounding.py --show-failures

# Run with embedding backend
PYTHONPATH=. python3 scripts/eval_rag_grounding.py --backend embedding --show-failures

# Fail if accuracy < 85%
PYTHONPATH=. python3 scripts/eval_rag_grounding.py --min-accuracy 0.85 --exit-nonzero
```

Eval cases live in `data/eval/rag_grounding.jsonl`.  Add rows to extend coverage:

```json
{"question": "off-topic query here", "must_abstain": true, "category": "off_topic"}
{"question": "What is the GROW model?", "must_abstain": false, "keywords": ["GROW", "Goal"], "category": "coaching_concept"}
```
