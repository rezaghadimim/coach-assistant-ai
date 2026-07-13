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
| RAG | Two-phase retrieval: situation (framework + collections) + expert solutions (multi-person); dual embed indices; E5 (Ollama) + optional cloud collection embed |
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
- **Expert Video Knowledge**: Per-person collections from transcripts/videos; multi-expert perspectives with attributed citations in chat

## Prerequisites

- Python 3.12+
- [Ollama](https://ollama.com) installed
- `ollama pull llama3.1:8b`
- `ollama pull karuniaperjuangan/multilingual-e5-small` — embeddings + tool routing + RAG stage-1
- RAG stage-2 reranking uses `fastembed` + `BAAI/bge-reranker-base` in-process (downloaded on first run; disable with `RAG_RERANK_ENABLED=false`)

Want to run on a smaller machine or swap in a 3–4B model? See
[docs/SMALL_MODELS.md](docs/SMALL_MODELS.md) — model inventory, swap-and-validate
checklist (eval scripts + acceptance bar), and the latency/context knobs
(`OLLAMA_NUM_CTX`, `OLLAMA_KEEP_ALIVE`, rerank pool sizes).

Health & monitoring: run `.venv/bin/python scripts/benchmark_pipeline.py` to smoke-test
every layer with latency budgets, and `./scripts/watch_health.sh` for instant
alerts when anything degrades — see [docs/BENCHMARKS.md](docs/BENCHMARKS.md).

## Getting Started

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Initialize private knowledge submodule, then ingest
#    See docs/knowledge/SETUP_PRIVATE_REPO.md
./scripts/setup_knowledge_private_repo.sh
python3 scripts/ingest.py

# 3. Configure auth (production) or enable debug mode (local dev)
#    All /api and /v1 endpoints require an API key and FAIL CLOSED without one.
#    Either set API_KEY=<secret> in .env and send it as `X-API-Key: <secret>`
#    (or `Authorization: Bearer <secret>`), or set DEBUG=true for local dev.
#    See docs/OPERATIONS.md.

# 4. Run API
python3 main.py

# 5. Run tests (CI-safe, no Ollama needed)
RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false \
  python3 -m pytest tests/

# 5. (Optional) Evaluate tool routing accuracy
PYTHONPATH=. python3 scripts/eval_tool_routing.py --backend token --show-errors
PYTHONPATH=. python3 scripts/eval_tool_routing.py --backend token --hard --show-errors

# 5b. (Optional) Evaluate RAG grounding / abstention quality
PYTHONPATH=. python3 scripts/eval_rag_grounding.py --show-failures

# 5c. (Optional) Evaluate LLM-router accuracy + hallucination rate (needs Ollama)
PYTHONPATH=. python3 scripts/eval_llm_router.py --show-errors

# 6. (Optional, Phase 5) Export sessions for fine-tuning
python3 scripts/export_training_data.py --output data/training/sessions.jsonl

# 7. (Optional, Phase 5) Fine-tune with Infinia dataset (run manually, not on a schedule)
#    First time: full pipeline (download → adapt → train → eval)
python3 scripts/run_tuning_pipeline.py --profile infinia-only --steps all --dry-run
#    See docs/FINETUNE.md for the full Infinia integration guide.
```

`data/knowledge/starter/` holds committed bootstrap docs. Your real documents
live in the **`coach-knowledge`** private repo, linked as a git submodule at
`data/knowledge/private/`. See
[Private knowledge setup](./docs/knowledge/SETUP_PRIVATE_REPO.md).

`data/tool-knowledge/` contains per-tool documentation and the routing corpus
(`examples/routing.jsonl`). This is tracked in git and is the source of truth for
tool disambiguation. Add examples here when you observe misrouting, then call
`POST /api/tools/reindex` to pick up changes without restarting.

## Docker / Open WebUI

```bash
# Run the full stack (API + Open WebUI) with Docker Compose
docker compose up --build
# Open WebUI → http://localhost:3000
# API docs    → http://localhost:8000/docs  (only when DEBUG=true; disabled in production)
```

The image runs uvicorn as a non-root user with a single worker (by design —
SQLite + in-process caches; scale with replicas), installs from the fully
pinned `requirements.lock`, and ships a container `HEALTHCHECK` against
`/health/live`. Details and rationale: [Operations guide](./docs/OPERATIONS.md).

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

All endpoints below except `/health*` and `/metrics` require the API key
header (`X-API-Key` or `Authorization: Bearer`) unless `DEBUG=true`.

### Native API
- `GET /health`
- `GET /health/live` — cheap liveness probe (container healthcheck)
- `GET /metrics` — Prometheus text (router deferrals, layer availability, latency)
- `POST /api/chat`
- `POST /api/ingest`
- `GET /api/collections` — list per-person knowledge collections
- `POST /api/collections` — create collection
- `POST /api/collections/{id}/sources` — register transcript, media, or URL
- `POST /api/collections/{id}/reindex` — reindex one collection
- `POST /api/collections/process-jobs` — run pending Whisper/YouTube jobs
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

- [Development guide](./docs/DEVELOPMENT.md) — setup, test, lint, roadmap workflow
- [Architecture](./docs/ARCHITECTURE.md)
- [Operations & Production Deployment](./docs/OPERATIONS.md) — auth, Docker hardening, reliability, CI gates
- [Implementation Plan](./docs/IMPLEMENTATION.md)
- [Tool Routing](./docs/TOOL_ROUTING.md)
- [RAG Pipeline](./docs/RAG.md)
- [Private knowledge repo setup](./docs/knowledge/SETUP_PRIVATE_REPO.md)
- [Memory System](./docs/MEMORY.md)
- [Open WebUI Integration](./docs/OPENWEBUI.md)
- [OpenRouter Integration](./docs/OPENROUTER.md)
- [Fine-tuning Guide](./docs/FINETUNE.md)
- [Architecture Decision Records](./docs/adr/README.md)
