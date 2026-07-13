# Module map (ownership, layering, state)

Documentation only — do not “fix” imports or move code based on this file alone. Scheduled fixes: reverse `main` import → T-035; public tokenizer API / end `_private` cross-imports → T-037.

Verified 2026-07-10.

---

## 1. Ownership

| Area | Responsibility |
|------|----------------|
| `app/api/` | HTTP routers: chat, OpenAI-compat, users, tools classify/reindex, collections, ingest, metrics, auth, briefing |
| `app/api/chat_pipeline.py` | Shared persist→history→direct-reply→prompt→generate→persist turn orchestration (`run_chat_turn`; used by `chat.py`; `openai_compat` in T-033) |
| `app/core/` | Orchestration + shared services: LLM loop, intents, tools, routers, formatter, config, providers, embed/rerank, scope, confirmations |
| `app/rag/` | Framework/collection retrieval indices, ingest/chunking, transcript parse, RAG rerank facade |
| `app/rag/embed_cache.py` | On-disk embedding cache I/O (versioned JSON envelope; per-corpus cache paths) |
| `app/knowledge/` | Collection SQLite store, filesystem ingest, media jobs (Whisper / yt-dlp) |
| `app/memory/` | Coach session SQLite (`MemoryStore`), session lifecycle, summarizer, training export |
| `app/models/` | Pydantic / API schemas |
| `app/training/` | Training-related helpers (if present) |
| `main.py` | FastAPI app factory, startup ingest, health/metrics helpers (`_layer_availability`, embed probe cache) |

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
2. **Known violation:** `app/api/metrics.py:124` imports `_layer_availability` from `main` (call-time circularity with `main` importing the metrics router). Do not add more `main` imports from `app/`. Fix scheduled: **T-035**.
3. **In-function imports** inside the cluster  
   `llm ↔ client_intents ↔ tools ↔ tool_router ↔ response_formatter ↔ llm_router ↔ model_registry`  
   are deliberate cycle-breaks. Never lift one to module level without verifying startup:  
   `python3 -c "import main"`.
4. **Never import `_underscored` names across modules** in new code. Existing violations (to be cleaned in **T-037**) include:
   - `tool_router` / `intent_kb` importing `_tf_cosine` / `_tokenize` from `app.rag.retriever`
   - cross-module use of `_truncate_words`, `_resolve_client_id` / `_fuzzy_resolve_client_id`, `_pii_preserved`

---

## 3. Module-level state registry

| State | Location | Notes |
|-------|----------|-------|
| `_framework_index`, `_collection_index` + embedding readiness flags; legacy `_index` / `_embedding_index_ready` | `app/rag/retriever.py:84-91` | Unlocked process globals; rebuilt at startup / ingest |
| `_pending_writes` | `app/core/confirmations.py:15` | Process-global, keyed by preview text (not user/session) — multi-tenant hazard (U-01) |
| Tool-router backends / availability | `app/core/tool_router.py:381-391` | `_token_backend`, `_embed_backend`, `_index_built`, `_embed_available`, `_rerank_available` |
| OpenRouter/local probe cache | `app/core/model_registry.py:73` | `_probe_cache` |
| Cross-encoder + probe | `app/core/rerank.py:38-43` | `_encoder`, `_encoder_model_name`, `_probe_ok` |
| Pooled HTTP clients | `app/core/llm_providers/http.py:23-24` | `_clients` per base URL |
| Deferral / near-miss counters | `app/core/routing_observability.py:32-35` | |
| Request counters | `app/api/metrics.py:24-26` | |
| Legacy `_sessions` + `store` / `session_manager` | `app/api/chat.py:32-35` | `MemoryStore` + `SessionManager` constructed at import |
| `KnowledgeStore` singleton | `app/api/collections.py:27` | Same DB file as memory store |
| Embed probe cache | `main.py:161` | `_embed_probe_cache` |
| Bound model id | `app/api/openai_compat.py:61` | `_MODEL_ID` at import |

---

## 4. Import-time side effects

| Module | Effect | Location |
|--------|--------|----------|
| `app/api/chat.py` | Instantiates `MemoryStore` (runs migrations, touches disk) + `SessionManager` | `:34-35` |
| `app/api/collections.py` | Instantiates `KnowledgeStore` on the same SQLite file | `:27` |
| `app/core/rerank.py` | Sets `HF_HUB_DISABLE_XET=1` **before** huggingface_hub/fastembed load | `:27` — order-sensitive |
| `app/core/intent_kb.py` | Precomputes intent vectors at import | `:196-197` (`for _spec in _INTENTS: _spec.index()`) |

**Rule:** adding new import-time I/O, network, or model loads requires maintainer sign-off. Prefer lazy init inside functions or FastAPI startup hooks.
