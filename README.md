# Life Coach AI

An AI-powered life coaching assistant that runs locally using open-source LLMs.

## Quick Summary

| Item | Detail |
|------|--------|
| LLM | Llama 3.1 8B (via Ollama) |
| RAG | Local chunk index + similarity retrieval |
| Backend | FastAPI (Python) |
| Database | SQLite (user memory + sessions) |
| UI | Open WebUI (via OpenAI-compatible API) |
| Hosting | Local machine / Docker |

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

## Docker / Open WebUI

```bash
# Run the full stack (API + Open WebUI) with Docker Compose
docker compose up --build
# Open WebUI → http://localhost:3000
# API docs    → http://localhost:8000/docs
```

See [Open WebUI Integration](./docs/OPENWEBUI.md) for details.

## API Endpoints

### Native API
- `GET /health`
- `POST /api/chat`
- `POST /api/ingest`
- `POST /api/users`
- `GET /api/users/{user_id}`
- `GET /api/sessions/{user_id}`
- `POST /api/sessions/{user_id}/new`

### OpenAI-Compatible (Open WebUI)
- `GET /v1/models`
- `POST /v1/chat/completions`

## Documentation

- [Architecture](./docs/ARCHITECTURE.md)
- [Implementation Plan](./docs/IMPLEMENTATION.md)
- [RAG Pipeline](./docs/RAG.md)
- [Memory System](./docs/MEMORY.md)
- [Open WebUI Integration](./docs/OPENWEBUI.md)
- [Fine-tuning Guide](./docs/FINETUNE.md)
- [Architecture Decision Records](./docs/adr/README.md)
