# Implementation Plan Status

## Completed

### Phase 1: Core Chat
- FastAPI app and health endpoint
- `POST /api/chat`
- Ollama integration
- Phase 1 tests

### Phase 2: RAG Pipeline (Backend)
- Document chunking and ingestion utilities
- Retrieval index and query logic
- `POST /api/ingest` endpoint
- Chat prompt grounding with retrieved context
- Phase 2 tests

### Phase 3: Memory System (Backend)
- SQLite schema + persistence layer
- User/session/message CRUD
- Session rollover + summary generation
- `POST /api/users`, `GET /api/users/{user_id}`
- `GET /api/sessions/{user_id}`, `POST /api/sessions/{user_id}/new`
- Phase 3 tests

## Remaining

### Phase 4: Web UI
- Build coach-facing UI (custom or Open WebUI integration)
- Add UI tests for end-to-end chat workflow

### Phase 5: Fine-tuning
- Collect enough production conversations
- Train and evaluate LoRA adapter
- Deploy fine-tuned model in Ollama

## Test Command

```bash
python3 -m unittest discover -s tests -p "test_*.py"
```
