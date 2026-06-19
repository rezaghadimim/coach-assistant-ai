# Architecture

## Overview

```text
Open WebUI (browser) → FastAPI ─────────────────────────────────────┐
                           |                                         │
                           ├─ /v1/chat/completions (model=local)  → Ollama (local)
                           ├─ /v1/chat/completions (model=cloud)  → OpenRouter (optional)
                           |                                         │
                           ├─ Local RAG Index (in-memory)           │
                           └─ SQLite Memory Store                   │
                                 (users, sessions, messages,        │
                                  client notes)                     │
```

The cloud OpenRouter provider is optional and only activated when
`OPENROUTER_API_KEY` is set and the availability probe succeeds.
The local Ollama provider is always the default.

## Implemented Components

### 1) Chat API (`app/api/chat.py`)

- Main endpoint: `POST /api/chat`
- Loads active session history from SQLite
- Injects optional RAG context, client profile, client notes, and session summary into system prompt
- Persists user/assistant messages
- LLM tool calling for client management (create client, add notes, look up profiles)

### 2) RAG Ingestion + Retrieval (`app/rag/`)

- `ingest.py`: document discovery + heading-aware chunking (`.txt`, `.md`, `.pdf`); merges `starter/` + `private/` (private wins on path collision)
- `knowledge_paths.py`: resolves configured starter and private directories
- `retriever.py`: two-stage retrieval — bi-encoder, TF cosine, or hybrid RRF (stage 1) followed by optional local cross-encoder reranking (stage 2); off-topic abstention; per-source deduplication before context assembly
- `reranker.py`: thin wrapper over `app/core/rerank.py` (fastembed `BAAI/bge-reranker-base`); graceful fallback when fastembed is unavailable
- `POST /api/ingest`: reindex starter + private knowledge directories

### 3) Memory System (`app/memory/`)

- `store.py`: SQLite schema + CRUD for users/sessions/messages/client_notes
- `session.py`: active session lifecycle and rollover
- `summarizer.py`: structured coaching session summary generation
- `app/api/users.py`: user, session, and client notes endpoints

### 4) Client Notes System

- Per-client documentation: stories, decisions, goals, progress notes
- CRUD API: create, list (with type filter), update, delete
- Auto-injected into system prompt for conversation continuity
- Decisions can be updated when revised

### 5) LLM Tool Calling (`app/core/tools.py`, `app/core/llm.py`)

- Provider-agnostic agentic loop (up to 5 iterations)
- Tools: `create_client`, `add_client_note`, `get_client`, `get_client_full`, `list_client_notes`, `list_clients`, `update_client_note`, `delete_client_note`, `delete_client`
- Tool results formatted per provider (Ollama uses `tool_name`; OpenRouter uses `tool_call_id`)
- Profile updates merge with existing client data (partial updates do not wipe fields)

### 6) LLM Provider Abstraction (`app/core/llm_providers/`)

- `types.py`: `LLMProvider` protocol, `CompletionResult`, `ToolCall` dataclasses
- `ollama.py`: Ollama `/api/chat` client (always active)
- `openrouter.py`: OpenRouter `/chat/completions` client (optional, opt-in via `OPENROUTER_API_KEY`)
- `app/core/model_registry.py`: virtual model IDs, provider resolution, and cached availability probe

### 7) Open WebUI Integration (`app/api/openai_compat.py`)

- `GET /v1/models`: dynamic model list — local always, cloud when probe passes
- `POST /v1/chat/completions`: routes by `model` field to the appropriate provider
- Streaming resolves tool calls first, then streams the final reply in chunks
- Cloud model returns HTTP 503 when OpenRouter is unavailable
- User identification via `user` field or `X-User-Id` header
- `Dockerfile` + `docker-compose.yml` for full-stack deployment
- Coach-branded UI via WEBUI_NAME environment variable

### 8) Coaching Scope Guardrails (`app/core/scope.py`)

- Deterministic off-topic detection before LLM calls
- Open WebUI auto-generated task prompts (follow-ups, title, tags) bypass the guard
- Fixed coaching-focused redirect for clearly non-coaching requests

### 9) Client Intent Detection (`app/core/client_intents.py`)

- Regex fast path for common client-management commands (lookup, create, notes)
- Write confirmation previews via `app/core/confirmations.py`
- Falls back to LLM tool calling when no intent matches

### 10) Fine-tuning Export (`app/memory/training_export.py`)

- `scripts/export_training_data.py`: export closed sessions from SQLite to JSONL
- Used as Phase 5 prep — see `[FINETUNE.md](FINETUNE.md)`

### 11) Tool Router (`app/core/tool_router.py`, `app/core/embeddings.py`, `app/core/lexicon.py`, `app/core/llm_router.py`)

- Classifies a coach message into the best-matching tool *before* the LLM using a layered approach
- **Synonym normalization** (`lexicon.py`): `normalize_for_routing()` expands out-of-vocabulary terms (visitor→client, table→list clients, dump→show/list) before any backend sees the query — additive, never destructive, router-local only
- **Three backends** (tried in order, fall-through on low confidence or error):
  - **rerank** — stage-1 embedding top-K recall + stage-2 fastembed cross-encoder precision (best for arbitrary phrasing)
  - **embedding** — Ollama dense cosine (multilingual, paraphrase-sensitive)
  - **token** — TF cosine (offline/CI-safe, always available)
- Backend selection via `TOOL_ROUTER_BACKEND`: `"token"` | `"embedding"` | `"auto"` (default; probes Ollama and fastembed at startup)
- **LLM router fallback** (`llm_router.py`): when all fast-path layers defer on a data-retrieval message, one compact LLM call picks a tool name (`{"tool": "..."}`) before falling into the full tool loop
- Corpus: `docs/tool-knowledge/examples/routing.jsonl` (130 examples); eval sets in `data/eval/`
- API: `POST /api/tools/classify` (exposes `rerank_score`, `backend`), `POST /api/tools/reindex`
- See `[TOOL_ROUTING.md](TOOL_ROUTING.md)` and [ADR-0007](adr/0007-ollama-embedding-tool-routing.md)

### 12) Response Formatter (`app/core/response_formatter.py`)

- Optional LLM pass that rephrases fast-path data replies into natural, human-friendly text
- Applied after the deterministic fast path fetches data — **only presentation changes, not data selection**
- Wired into **both** API entry points: `/api/chat` (`chat.py`) and `/v1/chat/completions` (`openai_compat.py`, used by Open WebUI)
- `is_formattable(reply)` gates the call: only successful read results (starting with the template prefix) are eligible; write previews (⏳/✅/❌), errors, greetings, and scope refusals pass through unchanged
- **PII validation**: every email and phone number in the source data must appear verbatim in the formatted output; any failure falls back to the deterministic template
- Gated by `RESPONSE_FORMATTER_ENABLED` (default `true`) — disable with `RESPONSE_FORMATTER_ENABLED=false`
- Benchmark: `scripts/benchmark_response_formatter.py` — measures latency overhead, PII preservation rate, and output length delta between OFF and ON modes
- See [ADR-0010](adr/0010-llm-response-formatter.md)

## Data Flow

1. Client sends `POST /api/chat {user_id, message}`
2. Backend gets/creates active session for `user_id`
3. Backend retrieves top matching chunks from local RAG index (stage-1 bi-encoder/token → stage-2 cross-encoder rerank → per-source dedup)
4. Backend composes system prompt with:
  - base coaching prompt
  - RAG context (if available)
  - user profile
  - client notes/stories/decisions
  - previous session summary
5. Backend resolves provider (Ollama or OpenRouter) from the virtual model ID
6. **Deterministic fast path** (in order, first match wins and returns):
  a. Pending write confirmation → confirm/cancel
   b. Regex extractors → profile update, create client, known read patterns
   c. Tool Router: synonym normalize → embedding top-K → cross-encoder rerank → embedding cosine → token cosine → param extract → execute_tool
   d. Intent KB (read-only patterns)
   e. LLM router fallback (one constrained call, data requests only) → param extract → execute_tool
   f. **Response Formatter** (optional, `RESPONSE_FORMATTER_ENABLED=true`): LLM rephrases the raw tool output into a natural reply; PII validation runs; falls back to template on failure
7. Full LLM tool-calling loop (hardened system prompt, max 5 iterations) for remaining cases
8. Dead-end guard: if the LLM returns only follow-up questions for a data request, rescues via direct-action path or returns a targeted clarification
9. Result is stored in SQLite

## Current File Map

```text
app/
├── api/
│   ├── chat.py
│   ├── ingest.py
│   ├── openai_compat.py
│   ├── tools.py           ← tool routing API (classify + reindex)
│   └── users.py
├── core/
│   ├── config.py
│   ├── embeddings.py      ← Ollama embedding client (E5 prefix, retry)
│   ├── lexicon.py         ← domain synonym normalization (router-local)
│   ├── llm_router.py      ← constrained LLM tool classifier (fallback)
│   ├── rerank.py          ← local fastembed cross-encoder (RAG + tool router)
│   ├── llm.py             ← tool loop, LLM router wiring, dead-end guard, formatter wiring
│   ├── response_formatter.py ← optional LLM formatting pass (PII validation, fallback)
│   ├── model_registry.py
│   ├── prompts.py
│   ├── scope.py
│   ├── tool_router.py     ← tool classification (token + embedding + rerank)
│   ├── tools.py
│   ├── client_intents.py
│   ├── confirmations.py
│   ├── intent_kb.py
│   └── llm_providers/
│       ├── types.py
│       ├── ollama.py
│       └── openrouter.py
├── rag/
│   ├── ingest.py
│   ├── retriever.py
│   └── reranker.py        ← RAG stage-2 reranker (fastembed / ONNX wrapper)
├── memory/
│   ├── session.py
│   ├── store.py
│   ├── summarizer.py
│   └── training_export.py
└── models/
    └── schemas.py         ← ToolMatchItem/ToolClassifyResponse include rerank_score

docs/
├── tool-knowledge/        ← per-tool docs + routing corpus (130 examples)
│   ├── create_client.md
│   ├── add_client_note.md
│   ├── ... (one per tool)
│   └── examples/
│       └── routing.jsonl

data/
└── eval/
    ├── tool_routing.jsonl       ← in-distribution eval set (59 rows)
    └── tool_routing_hard.jsonl  ← held-out out-of-vocab eval set (34 rows)

scripts/
├── ingest.py
├── export_training_data.py
├── eval_tool_routing.py              ← accuracy/F1/latency eval (--backend rerank, --hard)
├── benchmark_tool_routing.py        ← cross-backend comparison (token/embedding/rerank)
└── benchmark_response_formatter.py  ← formatter OFF vs ON: latency, PII preservation, char delta

tests/
├── test_lexicon.py                ← 24 normalization + token backend regression tests
├── test_tool_router_rerank.py     ← 12 rerank unit + integration tests (mocked)
├── test_llm_router.py             ← 18 LLM router parser + classify tests (mocked)
├── test_tool_router.py            ← token backend + 6 out-of-vocab cases via lexicon
├── test_tools_api.py              ← API schema fields + data-request guard tests
└── test_response_formatter.py    ← 19 formatter unit + integration tests (mocked provider)
```

