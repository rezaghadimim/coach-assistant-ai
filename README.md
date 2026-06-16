# Coach Assistant AI

Repository: [github.com/rezaghadimim/coach-assistant-ai](https://github.com/rezaghadimim/coach-assistant-ai)

An AI-powered coaching assistant that helps coaches manage their clients,
document each client's journey, and deliver actionable coaching guidance.
Runs locally using open-source LLMs.  **English-only interface.**

## Quick Summary

| Item | Detail |
|------|--------|
| LLM | Llama 3.1 8B (via Ollama) |
| Embed model | multilingual-e5-small (via Ollama, for tool routing + RAG stage-1) |
| RAG | Two-stage retrieval: E5 bi-encoder (Ollama) → local cross-encoder rerank (`BAAI/bge-reranker-base` via fastembed); grounding contract prevents hallucinated "facts" |
| Tool Routing | 307-example corpus; token → embedding → rerank → LLM router (structured JSON output at temp=0); 95.77% hard-set accuracy |
| Generation | Per-task temperatures: `0.0` for tool/data calls, `0.5` for coaching advice |
| Backend | FastAPI (Python) |
| Database | SQLite (client notes, sessions, memory) |
| UI | Open WebUI (via OpenAI-compatible API) |
| Hosting | Local machine / Docker |
| Language | English only |

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
- `ollama pull karuniaperjuangan/multilingual-e5-small` — embeddings + tool routing + RAG stage-1
- RAG stage-2 reranking uses `fastembed` + `BAAI/bge-reranker-base` in-process (downloaded on first run; disable with `RAG_RERANK_ENABLED=false`)

## Getting Started

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Ingest coaching documents
python3 scripts/ingest.py --docs-dir ./docs/knowledge/

# 3. Run API
python3 main.py

# 4. Run tests
python3 -m unittest discover -s tests -p "test_*.py"

# 5. (Optional) Evaluate tool routing accuracy
PYTHONPATH=. python3 scripts/eval_tool_routing.py --backend token --show-errors
PYTHONPATH=. python3 scripts/eval_tool_routing.py --backend token --hard --show-errors

# 5b. (Optional) Evaluate RAG grounding / abstention quality
PYTHONPATH=. python3 scripts/eval_rag_grounding.py --show-failures

# 6. (Optional, Phase 5) Export sessions for fine-tuning
python3 scripts/export_training_data.py --output data/training/sessions.jsonl

# 7. (Optional, Phase 5) Fine-tune with Infinia dataset (run manually, not on a schedule)
#    First time: full pipeline (download → adapt → train → eval)
python3 scripts/run_tuning_pipeline.py --profile infinia-only --steps all --dry-run
#    See docs/FINETUNE.md for the full Infinia integration guide.
```

`docs/knowledge/` is a local-only ingest folder. Keep your real source documents there
outside git; only a sample file is tracked in the repository.

`docs/tool-knowledge/` contains per-tool documentation and the routing corpus
(`examples/routing.jsonl`). This is tracked in git and is the source of truth for
tool disambiguation. Add examples here when you observe misrouting, then call
`POST /api/tools/reindex` to pick up changes without restarting.

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
- `POST /api/tools/classify` — debug tool routing for a message
- `POST /api/tools/reindex` — rebuild routing index after editing corpus
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
- [Tool Routing](./docs/TOOL_ROUTING.md)
- [RAG Pipeline](./docs/RAG.md)
- [Memory System](./docs/MEMORY.md)
- [Open WebUI Integration](./docs/OPENWEBUI.md)
- [OpenRouter Integration](./docs/OPENROUTER.md)
- [Fine-tuning Guide](./docs/FINETUNE.md)
- [Architecture Decision Records](./docs/adr/README.md)
