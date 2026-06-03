# Implementation Plan

> Step-by-step guide to building the Life Coach AI. Each phase is independent and testable.
>
> **Testing policy:** Testing is required for every phase. Each phase must include automated tests plus relevant manual smoke checks before it is considered complete.

## Phase 1: Core Chat (Week 1)

### Goal: Basic chat with Ollama working end-to-end

**Tasks:**
1. Set up project structure and `requirements.txt`
2. Create `app/core/config.py` with settings
3. Create `app/core/llm.py` — Ollama client wrapper
4. Create `app/core/prompts.py` — Life coaching system prompt
5. Create `app/api/chat.py` — POST /api/chat endpoint
6. Create `main.py` — FastAPI app entry point
7. Create `app/models/schemas.py` — Chat request/response models
8. Implement `tests/test_phase1_core_chat.py` automated tests:
   - `GET /health` responds with app health + model
   - `POST /api/chat` returns coaching response payload
   - Per-user in-memory session history is preserved across turns
   - LLM failures are surfaced as `502`
9. Manual smoke test: Send message → get coaching response

**Success Criteria:**
- `python3 -m unittest discover -s tests -p "test_*.py"` passes
- `curl POST /api/chat` returns a coaching-style response
- Response uses GROW model or other coaching frameworks

---

## Phase 2: RAG Pipeline (Week 2)

### Goal: Responses grounded in coach's actual materials

**Tasks:**
1. Create `scripts/ingest.py` — Read docs, chunk, embed, store
2. Create `app/rag/ingest.py` — Core chunking logic
3. Create `app/rag/retriever.py` — Query ChromaDB
4. Integrate RAG context into chat endpoint
5. Add `POST /api/ingest` endpoint for uploading new docs
6. Implement automated tests for ingestion and retrieval behavior
7. Manual smoke test: Ask question → response references coach's material

**Success Criteria:**
- Automated RAG tests pass
- Ingesting a PDF/text file works
- Chat responses include information from ingested docs

---

## Phase 3: Memory System (Week 3)

### Goal: System remembers clients across sessions

**Tasks:**
1. Create SQLite schema (users, sessions, messages)
2. Create `app/memory/store.py` — CRUD operations
3. Create `app/memory/session.py` — Session buffer
4. Create `app/memory/summarizer.py` — Auto-summarize
5. Create `app/api/users.py` — User management endpoints
6. Integrate memory into chat flow
7. Implement automated tests for memory CRUD and session context restoration
8. Manual smoke test: Multi-turn conversation remembers context

**Success Criteria:**
- Automated memory tests pass
- New session can reference previous session summary
- Client profile (goals, challenges) persists

---

## Phase 4: Web UI (Week 4)

### Goal: Clean interface for the coach to use

**Tasks:**
1. Choose: Open WebUI (fast) or custom (flexible)
2. If custom: Create minimal chat interface
3. Add client selector (dropdown of registered clients)
4. Add session history view
5. Style it professionally
6. Implement UI tests for core chat flow and client/session navigation
7. Manual smoke test: Full coaching session through browser

**Success Criteria:**
- Automated UI tests pass
- Coach can select client, chat, and see history
- Looks professional enough for client-facing use

---

## Phase 5: Fine-tuning (Month 2+)

### Goal: Model speaks in coach's voice

**Prerequisites:** 500+ real conversation examples collected from Phase 1-4

**Tasks:**
1. Export conversation data in training format
2. Rent GPU (RunPod/Lambda, ~$10)
3. Fine-tune with LoRA (see docs/FINETUNE.md)
4. Implement evaluation tests comparing fine-tuned model vs base model
5. Manual smoke test: Run prompt set and review quality/safety outputs
6. Deploy fine-tuned model to Ollama

**Success Criteria:**
- Evaluation tests show fine-tuned model quality improvement on target prompts
- Safety behavior remains acceptable on sensitive prompts

---

## Dependencies Between Phases

```
Phase 1 (Core) ──▶ Phase 2 (RAG) ──▶ Phase 4 (UI)
      │                                    │
      └──────────▶ Phase 3 (Memory) ───────┘
                                           │
                                           ▼
                                    Phase 5 (Fine-tune)
```

Phases 2 and 3 can be done in parallel after Phase 1.
