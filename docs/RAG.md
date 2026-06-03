# RAG Pipeline

## What is implemented

- Local ingestion of `.txt`, `.md`, and `.pdf` documents (`app/rag/ingest.py`)
- In-memory token-similarity retrieval index (`app/rag/retriever.py`)
- API endpoint to reindex documents (`POST /api/ingest`)
- Chat integration that injects retrieved chunks into system prompt

## Ingestion

```bash
python scripts/ingest.py --docs-dir ./docs/knowledge/
```

Or via API:

```bash
curl -X POST http://localhost:8000/api/ingest \
  -H "Content-Type: application/json" \
  -d '{"chunk_size":512,"chunk_overlap":50}'
```

## Retrieval

- Query is tokenized and matched against indexed chunks
- Scores are cosine similarity over token frequency vectors
- Top-k chunks are added to the coaching system prompt

## Testing

```bash
python3 -m unittest discover -s tests -p "test_*.py"
```
