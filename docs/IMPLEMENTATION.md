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

### Phase 2C: RAG Reranker — Cross-Encoder Two-Stage Retrieval

**Problem solved:** single-pass bi-encoder retrieval with `top_k=3` had no opportunity to re-score candidates; a query that was semantically close to several chunks had no second-pass signal to surface the most relevant one.

**Done:**
- [x] Two-stage `retrieve()`: stage-1 fetches `RAG_RETRIEVE_K=25` candidates; stage-2 cross-encoder reranks to `RAG_TOP_K=3`
- [x] `app/rag/reranker.py` — thin `sentence-transformers` `CrossEncoder` wrapper, module-level singleton, batch scoring, passage truncation, graceful fallback when package absent
- [x] Per-source deduplication: only the highest-scoring chunk per source file is kept
- [x] Configuration: `RAG_RETRIEVE_K`, `RAG_RERANK_ENABLED`, `RAG_RERANK_MODEL`, `RAG_RERANK_BATCH_SIZE`, `RAG_RERANK_MAX_PASSAGE_CHARS`
- [x] Optional dependency group: `uv sync --group rag-rerank` (or `pip install sentence-transformers`)
- [x] Startup probe + structured logging (`rag: rerank ready | model=...`)
- [x] `/health` endpoint gains `rerank: {enabled, model, available}`
- [x] Tests: `tests/test_rag_rerank.py` (12 tests, all mocked — CI-safe without the dependency group)
- [x] Docs: `RAG.md`, `ARCHITECTURE.md`, ADR-0008

**To operate:**
```bash
uv sync --group rag-rerank   # install sentence-transformers
RAG_RERANK_ENABLED=true RAG_RETRIEVE_K=25 python main.py
# startup log: rag: rerank ready | model=BAAI/bge-reranker-v2-m3
# per-request log: rag rerank | candidates=N final=M top_scores=[...]
```

See [`RAG.md`](RAG.md) for full configuration reference and [ADR-0008](adr/0008-cross-encoder-rag-reranker.md) for the rationale.

### Phase 2B: Tool Routing — Embedding-Based Disambiguation

**Problem solved:** messages like "Ali's age is 23" were reaching `add_client_note` (duplicate note on every message) instead of `create_client` (profile field merge).

**Done:**
- [x] Tool knowledge corpus: `docs/tool-knowledge/` (9 per-tool markdown docs + `routing.jsonl`)
- [x] Configuration: `TOOL_ROUTER_BACKEND`, `OLLAMA_EMBED_MODEL`, `TOOL_ROUTER_THRESHOLD`, etc.
- [x] Embedding client: `app/core/embeddings.py` — Ollama `/api/embeddings` with E5 prefix support
- [x] Tool router: `app/core/tool_router.py` — token + embedding backends, `classify_tool()`
- [x] Wiring: `_tool_router_action()` in `client_intents.py`, inserted before LLM tool calling
- [x] Eval dataset: `data/eval/tool_routing.jsonl` (~60 labeled utterances)
- [x] Eval script: `scripts/eval_tool_routing.py` — accuracy/precision/recall/F1 per tool
- [x] API: `POST /api/tools/classify`, `POST /api/tools/reindex`, health embed status
- [x] Tests: `test_tool_router.py`, `test_embeddings.py`, `test_tools_api.py`, extended `test_client_intents.py`
- [x] Docs: `TOOL_ROUTING.md`, ADR-0007

**To operate:**
```bash
ollama pull karuniaperjuangan/multilingual-e5-small
python scripts/eval_tool_routing.py --backend token --show-errors
```

See [`TOOL_ROUTING.md`](TOOL_ROUTING.md) for full guide.

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
