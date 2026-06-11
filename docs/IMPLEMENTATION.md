# Implementation Plan Status

## Completed

### Phase 1: Core Chat
- FastAPI app and health endpoint
- `POST /api/chat`
- Ollama integration
- Phase 1 tests

### Phase 2: RAG Pipeline — Knowledge Retrieval
> RAG is for **what the model knows**. Store documents, books, articles, and any content that may change or grow here — not in the model weights.
- Document chunking and ingestion utilities (`.txt`, `.md`, `.pdf`)
- In-memory token-similarity retrieval index
- `POST /api/ingest` endpoint to reindex the knowledge base
- Chat prompt grounding: top-k retrieved chunks injected into the system prompt
- Phase 2 tests

### Phase 3: Memory System (Backend)
- SQLite schema + persistence layer
- User/session/message CRUD
- Session rollover + summary generation
- `POST /api/users`, `GET /api/users/{user_id}`
- `GET /api/sessions/{user_id}`, `POST /api/sessions/{user_id}/new`
- Phase 3 tests

### Phase 4: Web UI — Open WebUI Integration
- OpenAI-compatible API layer (`GET /v1/models`, `POST /v1/chat/completions`)
- Streaming response support via SSE
- Per-user session routing through `user` field or `X-User-Id` header
- `Dockerfile` and `docker-compose.yml` for running the full stack
- Phase 4 tests

### Client Management Tools (Chat)
- Ollama tool-calling loop in `app/core/llm.py`
- Client-management tools in `app/core/tools.py`
- Wired into `/api/chat` and `/v1/chat/completions`
- Profile merge on partial `create_client` updates
- Tests in `tests/test_tools.py`

### Client Notes API
- SQLite `client_notes` table (stories, decisions, goals, progress)
- CRUD endpoints under `/api/clients/{user_id}/notes`
- Notes auto-injected into the chat system prompt
- Tests in `tests/test_client_notes.py`

### Coaching Scope Guardrails
- Deterministic off-topic detection in `app/core/scope.py`
- Open WebUI task prompts (follow-ups, title, tags) allowed through
- Tests in `tests/test_scope.py`

### Client Intent Detection
- Regex-based fast path for common client-management commands in `app/core/client_intents.py`
- Write confirmation flow via `app/core/confirmations.py`
- Intent knowledge base in `app/core/intent_kb.py`
- Tests in `tests/test_client_intents.py` and `tests/test_intent_kb.py`

### Optional OpenRouter Provider
- Cloud LLM routing when `OPENROUTER_API_KEY` is set
- Provider abstraction in `app/core/llm_providers/`
- Dynamic model registry and availability probe
- Tests in `tests/test_openrouter.py`
- See [`OPENROUTER.md`](OPENROUTER.md)

### Phase 5 Prep: Training Data Export
- `scripts/export_training_data.py` — export closed sessions from SQLite to JSONL
- Export logic in `app/memory/training_export.py`
- Tests in `tests/test_training_export.py`

## Remaining

### Phase 5: Fine-tuning (LoRA) — Behavior Adaptation
> Fine-tuning is for **how the model behaves**, not what it knows. Use this to teach the model the coach's tone, questioning style, and response patterns — not to inject knowledge that belongs in RAG.

**Done (tooling):**
- [x] Export script: `python scripts/export_training_data.py --output training_data.jsonl`

**Still to do (data + training):**
- [ ] Collect 500+ real coaching conversations (behavior examples, not documents)
- [ ] Validate that RAG + prompting isn't sufficient for your quality bar
- [ ] Train a LoRA adapter on coaching style, tone, and questioning strategy
- [ ] Evaluate adapter quality against the coaching methodology
- [ ] Deploy fine-tuned model in Ollama and point `ollama_model` at it

See [`FINETUNE.md`](FINETUNE.md) for the full guide, export options, and decision rules.

## Test Command

```bash
python3 -m unittest discover -s tests -p "test_*.py"
```
