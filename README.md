# Life Coach AI

An AI-powered life coaching assistant that runs locally using open-source LLMs.

## Quick Summary

| Item | Detail |
|------|--------|
| LLM | Llama 3.1 8B (via Ollama) |
| RAG | Local chunk index + similarity retrieval |
| Backend | FastAPI (Python) |
| Database | SQLite (user memory + sessions) |
| Hosting | Local machine |

## Prerequisites

- Python 3.11+
- [Ollama](https://ollama.com) installed
- `ollama pull llama3.1:8b`

## Getting Started

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Ingest coaching documents
python scripts/ingest.py --docs-dir ./docs/knowledge/

# 3. Run API
python main.py

# 4. Run tests
python3 -m unittest discover -s tests -p "test_*.py"
```

## API Endpoints

- `GET /health`
- `POST /api/chat`
- `POST /api/ingest`
- `POST /api/users`
- `GET /api/users/{user_id}`
- `GET /api/sessions/{user_id}`
- `POST /api/sessions/{user_id}/new`

## Documentation

- [Architecture](./docs/ARCHITECTURE.md)
- [Implementation Plan](./docs/IMPLEMENTATION.md)
- [RAG Pipeline](./docs/RAG.md)
- [Memory System](./docs/MEMORY.md)
- [Fine-tuning Guide](./docs/FINETUNE.md)
