# Module map (ownership, layering, state)

Documentation only — do not “fix” imports or move code based on this file alone.

Verified 2026-07-14 (post roadmap + RAG index COW close-out).

---

## 1. Ownership

| Area | Responsibility |
|------|----------------|
| `app/api/` | HTTP routers: chat, OpenAI-compat, users, tools classify/reindex, collections, ingest, metrics, auth, briefing |
| `app/api/chat_pipeline.py` | Shared persist→history→direct-reply→prompt→generate→persist turn orchestration (`run_chat_turn`; used by `chat.py` and non-streaming `openai_compat`) |
| `app/core/` | Orchestration + shared services: LLM loop, intents, tools, routers, formatter, config, providers, embed/rerank, scope, confirmations, health |
| `app/core/health.py` | Layer probes / embed-probe cache / `layer_availability` (used by metrics; no `main` import) |
| `app/rag/` | Framework/collection retrieval indices, ingest/chunking, transcript parse, RAG rerank facade |
| `app/rag/embed_cache.py` | On-disk embedding cache I/O (versioned JSON envelope; per-corpus cache paths) |
| `app/rag/formatting.py` | Citation/prompt formatting for retrieved chunks (two-phase coach context strings) |
| `app/knowledge/` | Collection SQLite store, filesystem ingest, media jobs (Whisper / yt-dlp) |
| `app/memory/` | Coach session SQLite (`MemoryStore`), session lifecycle, summarizer, training export |
| `app/models/` | Pydantic / API schemas |
| `app/training/` | Training-related helpers (if present) |
| `main.py` | FastAPI app factory, lifespan startup ingest / tool-router build / rerank warm — not a library import target |

---

## 2. Layering and import rules

Intended direction:

```text
api  →  core  →  (rag | knowledge | memory)
         ↑
    models, config, observability  (importable from anywhere in app/)
```

**Rules**

1. **`core` must not import from `api`.**
2. **Do not import from `main` inside `app/`.** Health lives in `app.core.health` (T-035). Metrics must not depend on the entrypoint.
3. **Orchestration cluster** (`llm`, `client_intents`, `tools`, `tool_router`, `response_formatter`, `llm_router`, `model_registry`) is an **import DAG today**, not a circular tangle. Many in-function imports are optional/heavy deps or historical style. Lifting a peer import to module level is allowed if `python -c "import main"` (with the project venv) still succeeds. Soft pairs that still need lazy/`TYPE_CHECKING` care: `retriever` ↔ `reranker`, `tool_router` ↔ `routing_observability`.
4. **Prefer public names cross-module.** Use `tokenize` / `tf_cosine` from `app.rag.retriever` (T-037). Do not add new cross-module `_underscored` imports; existing ones (`_truncate_words`, `_resolve_client_id`, `_pii_preserved`, …) are debt to shrink carefully.

---

## 3. Module-level state registry

| State | Location | Notes |
|-------|----------|-------|
| Framework/collection index generations + embedding readiness | `app/rag/retriever.py` | Process globals published via **copy-on-write** (`_publish_index` / `_snapshot_index` under `_index_lock`). Readers snapshot then score outside the lock. Legacy aliases `_index` / `_embedding_index_ready` track framework. |
| `_pending_writes` | `app/core/confirmations.py` | Process-global, keyed by preview text. Acceptable under **single-tenant per instance** (U-01); unsafe if multiple coaches share one process. |
| Tool-router backends / availability | `app/core/tool_router.py` | Build serialized by `_build_lock` |
| OpenRouter/local probe cache | `app/core/model_registry.py` | `_probe_cache` |
| Cross-encoder + probe | `app/core/rerank.py` | `_encoder`, lock-guarded |
| Pooled HTTP clients | `app/core/llm_providers/http.py` | `_clients` per base URL |
| Deferral / near-miss counters | `app/core/routing_observability.py` | Process metrics |
| Request counters | `app/api/metrics.py` | Process metrics |
| Legacy `_sessions` + `store` / `session_manager` | `app/api/chat.py` | `MemoryStore` + `SessionManager` constructed at **import** (tests redirect `MEMORY_DB_PATH` in conftest first) |
| `KnowledgeStore` singleton | `app/api/collections.py` | Same DB file as memory store; import-time init |
| Embed probe cache | `app/core/health.py` | Moved from `main` in T-035 |
| Bound model id | `app/api/openai_compat.py` | `_MODEL_ID` at import |

**Deployment assumption:** uvicorn `--workers 1` (Dockerfile / OPERATIONS). Scale with separate container replicas, not in-process workers.

---

## 4. Import-time side effects

| Module | Effect | Location |
|--------|--------|----------|
| `app/api/chat.py` | Instantiates `MemoryStore` (migrations, disk) + `SessionManager` | store / session_manager module attrs |
| `app/api/collections.py` | Instantiates `KnowledgeStore` on the same SQLite file | module `store` |
| `app/core/rerank.py` | Sets `HF_HUB_DISABLE_XET=1` **before** huggingface_hub/fastembed load | order-sensitive |
| `app/core/intent_kb.py` | Precomputes intent vectors at import | `_INTENTS` loop |

**Verdict (2026-07-14):** import-time store init and `chat.reset_runtime_state()` (test helper that clears DB) are **documented DX/test coupling**, not current production defects under single-worker deploy. Do not refactor unless a concrete failing path appears. Prefer lazy init for *new* import-time I/O; require maintainer sign-off for new network/model loads at import.

**Rule:** adding new import-time I/O, network, or model loads requires maintainer sign-off. Prefer lazy init inside functions or FastAPI startup hooks.
