# Coach Assistant AI

Repository: [github.com/rezaghadimim/coach-assistant-ai](https://github.com/rezaghadimim/coach-assistant-ai)

An AI-powered coaching assistant that helps coaches manage their clients,
document each client's journey, and deliver actionable coaching guidance.
Runs locally using open-source LLMs.

## Quick Summary

| Item | Detail |
|------|--------|
| LLM | Llama 3.1 8B (via Ollama) |
| RAG | Local chunk index + similarity retrieval |
| Backend | FastAPI (Python) |
| Database | SQLite (client notes, sessions, memory) |
| UI | Open WebUI (via OpenAI-compatible API) |
| Hosting | Local machine / Docker |

## Key Features

- **Client Documentation**: Each conversation serves as a living record for each client
- **Chat-Based Client Management**: Register clients, save notes, and look up profiles via natural language in chat
- **Story & Decision Tracking**: Add notes, stories, and decisions per client — always accessible
- **Session Continuity**: Coach references past sessions, notes, and decisions automatically
- **Actionable Coaching**: Direct coaching advice using GROW model and other frameworks
- **Progress Monitoring**: Track goals, action items, and outcomes across sessions
- **Coaching-only Scope**: Stays focused on coaching — off-topic requests are declined and redirected, and follow-up/starter suggestions remain coaching-focused

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

# 5. (Optional, Phase 5) Export sessions for fine-tuning
python scripts/export_training_data.py --output training_data.jsonl
```

`docs/knowledge/` is a local-only ingest folder. Keep your real source documents there
outside git; only a sample file is tracked in the repository.

## Docker / Open WebUI

```bash
# Run the full stack (API + Open WebUI) with Docker Compose
docker compose up --build
# Open WebUI → http://localhost:3000
# API docs    → http://localhost:8000/docs
```

See [Open WebUI Integration](./docs/OPENWEBUI.md) for details.

## Optional Cloud Testing (OpenRouter)

Set `OPENROUTER_API_KEY` in a `.env` file (see `.env.example`) to unlock an
optional second model in Open WebUI that routes to a cloud LLM via
[OpenRouter](https://openrouter.ai). The local Ollama model remains the default
— the cloud model only appears in the picker when the API key is valid.

```env
OPENROUTER_API_KEY=sk-or-v1-your-key-here
OPENROUTER_MODEL=openai/gpt-4o-mini   # or any model on openrouter.ai/models
```

See [OpenRouter Integration](./docs/OPENROUTER.md) for full setup instructions,
model options, cost reference, and troubleshooting.

## API Endpoints

### Native API
- `GET /health`
- `POST /api/chat`
- `POST /api/ingest`
- `POST /api/users`
- `GET /api/users/{user_id}`
- `GET /api/sessions/{user_id}`
- `POST /api/sessions/{user_id}/new`

### Client Notes (Documentation per client)
- `POST /api/clients/{user_id}/notes` — Add a note (story, decision, goal, progress)
- `GET /api/clients/{user_id}/notes` — List all notes (filterable by type)
- `PUT /api/clients/{user_id}/notes/{note_id}` — Update a note
- `DELETE /api/clients/{user_id}/notes/{note_id}` — Delete a note

### OpenAI-Compatible (Open WebUI)
- `GET /v1/models`
- `POST /v1/chat/completions`

## Documentation

- [Architecture](./docs/ARCHITECTURE.md)
- [Implementation Plan](./docs/IMPLEMENTATION.md)
- [RAG Pipeline](./docs/RAG.md)
- [Memory System](./docs/MEMORY.md)
- [Open WebUI Integration](./docs/OPENWEBUI.md)
- [OpenRouter Integration](./docs/OPENROUTER.md)
- [Fine-tuning Guide](./docs/FINETUNE.md)
- [Architecture Decision Records](./docs/adr/README.md)
