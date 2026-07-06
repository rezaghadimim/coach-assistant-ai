# Architecture

## Overview

```text
Open WebUI (browser) → FastAPI ─────────────────────────────────────┐
                           |                                         │
                           ├─ /v1/chat/completions (model=local)  → Ollama (local)
                           ├─ /v1/chat/completions (model=cloud)  → OpenRouter (optional)
                           |                                         │
                           ├─ Local RAG Index (in-memory)           │
                           │    framework_index + collection_index    │
                           ├─ Knowledge Collections API               │
                           └─ SQLite Memory Store                   │
                                 (users, sessions, messages,        │
                                  client notes, knowledge metadata)  │
```

The cloud OpenRouter provider is optional and only activated when
`OPENROUTER_API_KEY` is set and the availability probe succeeds.
The local Ollama provider is always the default.

## Implemented Components

### 1) Chat API (`app/api/chat.py`)

- Main endpoint: `POST /api/chat`
- Loads active session history from SQLite
- Injects optional **two-phase RAG context** (situation + expert perspectives), client profile, client notes, and session summary into system prompt
- Persists user/assistant messages
- LLM tool calling for client management (create client, add notes, look up profiles)

### 2) RAG Ingestion + Retrieval (`app/rag/`)

- `ingest.py`: document discovery + heading-aware chunking (`.txt`, `.md`, `.pdf`); merges `starter/` + `private/` (private wins on path collision); extended `DocumentChunk` with collection/timestamp metadata
- `transcript.py`: SRT/VTT parsing and time-aware chunking for video guides
- `knowledge_paths.py`: resolves configured starter and private directories
- `retriever.py`: **dual indices** (`framework_index`, `collection_index`); two-phase `retrieve_coach_context()` for chat; legacy `retrieve()` on framework corpus; bi-encoder, TF cosine, or hybrid RRF (stage 1) + cross-encoder rerank (stage 2); `diversify_by_collection()` for multi-expert phase 2
- `reranker.py`: thin wrapper over `app/core/rerank.py` (fastembed `BAAI/bge-reranker-base`); raises on scoring failure — the retriever falls back to stage-1 ordering with original stage-1 scores (filtered by `RAG_MIN_SCORE`, not the rerank floor), and a failed model load is cached so later queries skip the reranker cheaply
- `POST /api/ingest`: reindex starter + private + all collections
- `app/knowledge/`: collection store, filesystem ingest, media jobs (Whisper, yt-dlp)
- `app/api/collections.py`: collection CRUD, source registration, reindex, `process-jobs`
- `app/core/embed_providers/`: Ollama, OpenRouter, OpenAI embedding backends

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
- Corpus: `data/tool-knowledge/examples/routing.jsonl` (130 examples); eval sets in `data/eval/`
- API: `POST /api/tools/classify` (exposes `rerank_score`, `backend`), `POST /api/tools/reindex`
- **Deferral observability**: when all fast-path backends defer, `classify_tool()` records top-3 candidates in `app/core/routing_observability.py`; near-misses (top score ≥ `TOOL_ROUTER_NEAR_MISS_SCORE`, default 0.25) are logged at INFO and exposed on `/health` under `tool_router`
- See `[TOOL_ROUTING.md](TOOL_ROUTING.md)` and [ADR-0007](adr/0007-ollama-embedding-tool-routing.md)

### 12) Response Formatter (`app/core/response_formatter.py`)

- Optional LLM pass that rephrases fast-path data replies into natural, human-friendly text
- Applied after the deterministic fast path fetches data — **only presentation changes, not data selection**
- Wired into **both** API entry points: `/api/chat` (`chat.py`) and `/v1/chat/completions` (`openai_compat.py`, used by Open WebUI)
- `is_formattable(reply)` gates the call: only successful read results (starting with the template prefix) are eligible; write previews (⏳/✅/❌), errors, greetings, and scope refusals pass through unchanged
- **PII validation**: every email and phone number in the formatted output must exist verbatim in the source data; regional phone formats (bare digits, `09…`, international spacing) are detected via `_extract_phones()`, and ISO dates (note timestamps) are masked first so they are not mistaken for phone numbers
- **Per-tool hints**: `format_data_reply(..., tool=, hint=)` applies deterministic formatters for notes lists, compact client lists, and single profile fields **before** the optional LLM pass — common reply shapes resolve in ~16 µs with guaranteed PII instead of an ~870 ms LLM call; tool-specific LLM guidance is appended when deterministic formatting does not apply
- Gated by `RESPONSE_FORMATTER_ENABLED` (default `true`) — disable with `RESPONSE_FORMATTER_ENABLED=false`
- Benchmarks: `scripts/benchmark_response_formatter.py` (template vs LLM pass) and `scripts/benchmark_formatter_hints.py` (per-tool deterministic fast path: hit-rate, latency saved, PII)
- See [ADR-0010](adr/0010-llm-response-formatter.md)

### 13) Security & Operations Layer (2026-07 production-readiness hardening)

- **API-key auth** (`app/api/auth.py`): every `/api` and `/v1` router requires `X-API-Key` or `Authorization: Bearer`; fails closed when `API_KEY` is unset unless `DEBUG=true`; `/health*` and `/metrics` stay open
- **Interactive docs** (`/docs`, `/redoc`, `/openapi.json`) disabled unless `DEBUG=true`
- **Prompt fencing** (`app/api/chat.py`): notes/summaries sanitized and wrapped in `<client_data>` / `<previous_session_summary>` fences with an untrusted-data preamble
- **Ingest validation** (`app/knowledge/jobs.py`, `app/api/collections.py`): https + YouTube host allowlist, `--` before yt-dlp URLs, `MEDIA_ROOT` containment, `source_id` pattern + path-containment checks
- **Reliability**: pooled per-base-URL `httpx.AsyncClient` with bounded retries (`app/core/llm_providers/http.py`), per-request deadline (`REQUEST_TIMEOUT_S` → 504), background off-request-path session summarization, SQLite WAL + busy_timeout, `PRAGMA user_version` migrations
- **Metrics** (`app/api/metrics.py`): Prometheus text endpoint — router deferral counters, per-layer availability, request-duration summary
- Full rationale and deployment guidance: [OPERATIONS.md](OPERATIONS.md)

## Data Flow

1. Client sends `POST /api/chat {user_id, message}` (authenticated via `X-API-Key`)
2. Backend gets/creates active session for `user_id`
3. Backend runs **two-phase RAG** when enabled: phase 1 (situation) across framework + collection indices; phase 2 (expert solutions) across collections with diversity across people
4. Backend composes system prompt with:
  - base coaching prompt
  - RAG context — situation + expert perspectives (if available)
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
   f. **Response Formatter** (on by default): LLM rephrases the raw tool output into a natural reply; PII validation runs; falls back to template on failure. Disable with `RESPONSE_FORMATTER_ENABLED=false`.
7. Full LLM tool-calling loop (hardened system prompt, max 5 iterations) for remaining cases
8. Dead-end guard: if the LLM returns only follow-up questions for a data request, rescues via direct-action path or returns a targeted clarification
9. Result is stored in SQLite

## Current File Map

```text
app/
├── api/
│   ├── auth.py            ← API-key dependency (fail-closed)
│   ├── chat.py
│   ├── collections.py     ← per-person video knowledge API
│   ├── ingest.py
│   ├── metrics.py         ← Prometheus text endpoint
│   ├── openai_compat.py
│   ├── tools.py           ← tool routing API (classify + reindex)
│   └── users.py
├── core/
│   ├── config.py
│   ├── embed_providers/   ← Ollama, OpenRouter, OpenAI embed backends
│   ├── embeddings.py      ← embedding facade (RAG + tool router)
│   ├── lexicon.py         ← domain synonym normalization (router-local)
│   ├── llm_router.py      ← constrained LLM tool classifier (fallback)
│   ├── rerank.py          ← local fastembed cross-encoder (RAG + tool router)
│   ├── llm.py             ← tool loop, LLM router wiring, dead-end guard, formatter wiring
│   ├── response_formatter.py ← optional LLM formatting pass (PII validation, per-tool hints, fallback)
│   ├── routing_observability.py ← deferral ring buffer + /health stats
│   ├── model_registry.py
│   ├── prompts.py
│   ├── scope.py
│   ├── tool_router.py     ← tool classification (token + embedding + rerank)
│   ├── tools.py
│   ├── client_intents.py
│   ├── confirmations.py   ← structured pending-write registry + confirm replay
│   ├── intent_kb.py
│   ├── tool_json.py       ← tolerant tool-call JSON parsing (shared)
│   └── llm_providers/
│       ├── types.py
│       ├── http.py        ← pooled AsyncClient per base URL + retry
│       ├── ollama.py
│       └── openrouter.py
├── rag/
│   ├── ingest.py
│   ├── transcript.py      ← SRT/VTT parse + time-aware chunks
│   ├── retriever.py
│   └── reranker.py        ← RAG stage-2 reranker (fastembed / ONNX wrapper)
├── knowledge/
│   ├── store.py           ← collections / sources / chunks (SQLite)
│   ├── ingest.py          ← filesystem collection discovery
│   └── jobs.py            ← Whisper + yt-dlp media pipeline
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
├── knowledge/
│   └── collections/       ← per-person video/transcript corpora
└── eval/
    ├── tool_routing.jsonl       ← in-distribution eval set
    ├── tool_routing_hard.jsonl  ← held-out out-of-vocab eval set
    └── llm_router.jsonl         ← LLM-router eval set incl. data-shaped "none" rows (abstention)

scripts/
├── ingest.py
├── export_training_data.py
├── eval_tool_routing.py              ← accuracy/F1/latency eval (--backend rerank, --hard)
├── eval_llm_router.py                ← LLM-router accuracy + hallucination-rate eval (needs Ollama)
├── benchmark_tool_routing.py        ← cross-backend comparison (token/embedding/rerank)
└── benchmark_response_formatter.py  ← formatter OFF vs ON: latency, PII preservation, char delta

tests/
├── test_lexicon.py                ← 24 normalization + token backend regression tests
├── test_tool_router_rerank.py     ← 12 rerank unit + integration tests (mocked)
├── test_llm_router.py             ← 18 LLM router parser + classify tests (mocked)
├── test_eval_llm_router.py        ← LLM-router eval set integrity + trap coverage (CI-safe)
├── test_llm_router_integration.py ← live abstention regression: acc ≥ 0.90, halluc ≤ 0.10 (optional)
├── test_tool_router.py            ← token backend + 6 out-of-vocab cases via lexicon
├── test_tools_api.py              ← API schema fields + data-request guard tests
├── test_response_formatter.py    ← formatter unit + integration tests (mocked provider)
├── test_routing_observability.py ← deferral recording + /health tool_router stats
├── test_transcript_parser.py     ← SRT/VTT + timestamp chunking
├── test_collection_ingest.py     ← filesystem collection ingest
├── test_two_phase_retrieval.py   ← coach retrieval phases + diversity
├── test_embed_providers.py       ← embed provider factory
└── test_knowledge_jobs.py        ← media job offline tests
```

