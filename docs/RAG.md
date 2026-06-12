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
  - **Stage 2** — optional cross-encoder reranker (`app/rag/reranker.py`) narrows pool to final `RAG_TOP_K` (default 3)
- Source-level deduplication: only the highest-scoring chunk per source file reaches context
- API endpoint to reindex documents (`POST /api/ingest`)
- Chat integration that injects retrieved chunks into system prompt

## Retrieval pipeline

```
Query
  → Stage 1: bi-encoder / TF cosine  (retrieve_k=25 candidates)
  → Stage 2: cross-encoder reranker  (optional, narrows to top_k=3)
  → source deduplication
  → format_retrieval_context()
  → build_system_prompt()
  → LLM
```

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

The cross-encoder reranker is an **optional dependency group**. Without it the
pipeline falls back gracefully to stage-1 ordering — no configuration change
required.

To enable:

```bash
# local / development
uv sync --group rag-rerank

# or with pip
pip install sentence-transformers
```

The default model is `BAAI/bge-reranker-v2-m3` (multilingual; aligns with the
E5-small embedding model used in tool routing). It is downloaded automatically
on first use.

Docker users who want reranking should add the following line to the `Dockerfile`
before the `CMD` line:

```dockerfile
RUN pip install --no-cache-dir sentence-transformers
```

### Key environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RAG_RETRIEVE_K` | `25` | Stage-1 candidate pool size |
| `RAG_RERANK_ENABLED` | `true` | Enable/disable cross-encoder reranking |
| `RAG_RERANK_MODEL` | `BAAI/bge-reranker-v2-m3` | HuggingFace model ID |
| `RAG_RERANK_BATCH_SIZE` | `16` | Pairs per forward pass |
| `RAG_RERANK_MAX_PASSAGE_CHARS` | `2000` | Passage truncation before scoring |
| `RAG_TOP_K` | `3` | Final number of chunks injected into prompt |

Reranker availability is reported in the `/health` endpoint under the `rerank` key.

## Testing

```bash
python3 -m unittest discover -s tests -p "test_*.py"
```

New reranker-specific tests live in `tests/test_rag_rerank.py`. All tests mock
`CrossEncoder` so they run in CI without the dependency group installed.
