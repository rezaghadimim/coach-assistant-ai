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

## Remaining

### Phase 5: Fine-tuning (LoRA) — Behavior Adaptation
> Fine-tuning is for **how the model behaves**, not what it knows. Use this to teach the model the coach's tone, questioning style, and response patterns — not to inject knowledge that belongs in RAG.
- Collect 500+ real coaching conversations (behavior examples, not documents)
- Train a LoRA adapter on coaching style, tone, and questioning strategy
- Evaluate adapter quality against the coaching methodology
- Deploy fine-tuned model in Ollama
- See [`FINETUNE.md`](FINETUNE.md) for full guide and decision rules

## Test Command

```bash
python3 -m unittest discover -s tests -p "test_*.py"
```
