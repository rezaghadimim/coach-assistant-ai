# Repository Audit — Hallucination-Risk Analysis

**Analyzed at commit:** `5456607` (branch `main`), 2026-07-10.
**Method:** full read of `app/`, `main.py`, `tests/conftest.py`, `pyproject.toml`, CI workflow, all `docs/` + ADRs; sampled test files and scripts.
**Purpose:** ground truth for the roadmap in [README.md](README.md). Every task cites risk IDs (`R-xx`) and unknown IDs (`U-xx`) from this file.

Rules used throughout: facts below are **VERIFIED** against source (with `file:line` evidence) unless listed under **Unknowns**. Nothing here is inferred from documentation alone — several docs are stale (see R-01).

---

## 1. Verified architecture summary

- **Stack:** FastAPI + Ollama (Llama 3.1 8B) + SQLite; Open WebUI as UI via an OpenAI-compatible API. No ORM — raw `sqlite3`. No vector DB — in-memory linear-scan indices.
- **Entry points:** `POST /api/chat` (`app/api/chat.py:153`) and `POST /v1/chat/completions` (`app/api/openai_compat.py:340`). Both run: deterministic fast path `try_direct_reply_with_meta` (`app/core/llm.py:331`) → fallback `generate_response` (`app/core/llm.py:384`) with `skip_direct_reply=True`.
- **Deterministic fast path:** `app/core/client_intents.py` (regex NLU) → `app/core/tool_router.py` (token/embedding/rerank classify) → `app/core/intent_kb.py` fallback. LLM path: `app/core/llm_router.py` (structured-JSON classify) or agentic tool loop (max 5 iterations, `llm.py:541`).
- **Providers:** `app/core/model_registry.py` resolves Ollama / OpenAI-compat / OpenRouter (`app/core/llm_providers/`). `OPENAI_MODEL` set ⇒ local provider becomes OpenAI (`model_registry.py:82`).
- **RAG:** two in-memory corpora `framework` + `collection` (`app/rag/retriever.py:84-85`); two-phase coach retrieval (`retriever.py:325`); embedding-vector JSON caches under `data/` are the only persisted retrieval state — indices rebuild every process start (startup `main.py:56-79`).
- **Persistence:** one SQLite file (`data/coach_assistant.db`) written by **two** store classes: `MemoryStore` (`app/memory/store.py`, versioned migrations, WAL) and `KnowledgeStore` (`app/knowledge/store.py`, no migrations, no WAL).
- **Auth:** fail-closed API key (`app/api/auth.py`); `DEBUG=true` bypass only when no key configured. `/metrics` and `/health*` unauthenticated by design (`main.py:134-138`).
- **CI:** `.github/workflows/tests.yml` — Python 3.12, `ruff check .`, `mypy app/`, pytest with `RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false`, coverage floor 75%.

---

## 2. Risk register

Severity: ⚠️⚠️⚠️ = will actively cause a small model to produce wrong code; ⚠️⚠️ = likely to; ⚠️ = friction/latent.

### R-01 ⚠️⚠️⚠️ Documentation states false facts
A model that trusts docs will be wrong:
- Routing corpus size: real count is `wc -l data/tool-knowledge/examples/routing.jsonl` = **363**. Docs claim **130** (`docs/ARCHITECTURE.md:110,215`) or **307** (`docs/IMPLEMENTATION.md:157,251,261`, `docs/BENCHMARKS.md:134`, `docs/SMALL_MODELS.md:67`, `docs/TOOL_ROUTING.md:139`).
- `docs/ARCHITECTURE.md:214-220` places `tool-knowledge/` under `docs/` — real path is `data/tool-knowledge/`. Same doc has the correct path at line 110 (internal contradiction).
- `docs/MEMORY.md:34-40` lists **5** chat tools; `app/core/tools.py` defines **9** (`TOOL_DEFINITIONS`, `tools.py:237`).
- `docs/IMPLEMENTATION.md:215-224` claims non-PII fabrication is an open "residual gap"; guardrail E (`_notes_grounded`, `app/core/llm.py:144`) closes it and is tested (`tests/test_llm_guardrails.py`).
- `docs/ARCHITECTURE.md:37` files `knowledge_paths.py` under `app/rag/`; real location `app/core/knowledge_paths.py`.

### R-02 ⚠️⚠️ Broken/misleading pointers
- `pyproject.toml:65` references `docs/PRODUCTION_READINESS_CHECKLIST.md`; file lives at `docs/archive/PRODUCTION_READINESS_CHECKLIST.md`.
- `.gitmodules` names the submodule `docs/knowledge/private` while its path is `data/knowledge/private`.
- ADRs 0001–0005 carry placeholder date `2024-01-01`; real ADR activity starts 2026-06 (0006–0011).

### R-03 ✅ Resolved — Python version story is consistent
Formerly: `.python-version` 3.12 vs CI/Docker/`requires-python`/ruff targeting 3.11 while mypy used 3.12. **Resolved:** the project is **Python 3.12 only** across local, CI, Docker (`python:3.12-slim`), `requires-python >=3.12`, ruff `py312`, and mypy. (Still true and separate: CI/Docker install from `requirements*.txt`/`requirements.lock`, **not** from pyproject `[dependency-groups]`.)

### R-04 ⚠️⚠️⚠️ Chat pipeline duplicated across two endpoints
The persist→history→direct-reply→prompt→generate→append-ideas→persist→schedule-summary sequence is implemented twice: `app/api/chat.py:160-206` and `app/api/openai_compat.py:394-483`. They already diverge: openai_compat gates direct-reply formatting on `response_formatter_enabled` (`openai_compat.py:152`), chat.py does not; chat.py keeps a legacy `_sessions` dict (`chat.py:32,165,201`). Any pipeline edit must be mirrored by hand.

### R-05 ⚠️⚠️⚠️ Cross-file magic strings that must match exactly
- `"Here are the details on file:\n\n"` defined in `app/core/llm.py:249` **and** `app/core/response_formatter.py:31` (`_DATA_REPLY_PREFIX`); `is_formattable` (`response_formatter.py:122`) gates on it. Drift silently disables all data-reply formatting.
- `"No notes on file."` produced `app/core/tools.py:175`, matched `app/core/llm.py:144` (guardrail E).
- `"Registered clients:"` produced `tools.py:621`, matched `response_formatter.py:137,281`.
- `"pending confirmation"` produced `tools.py:148,161,199`, matched `app/core/confirmations.py:167`.
- Emoji status markers `⏳/✅/❌` are semantic (documented only in `tools.py:16-33` docstring).

### R-06 ⚠️⚠️⚠️ Enums duplicated by hand
- The 9 tool names live in **4** places: `tools.TOOL_DEFINITIONS` (`tools.py:237`), `tools._WRITE_TOOLS` (`tools.py:53`), `llm_router._KNOWN_TOOLS` (`llm_router.py:35`), `_ROUTER_SCHEMA` enum (`llm_router.py:106`). Adding a tool requires 4 synchronized edits (plus a tool card in `data/tool-knowledge/` and routing examples).
- Note-type enum `{general,story,decision,goal,progress}`: `tools._VALID_NOTE_TYPES` (`tools.py:52`) + repeated inline in tool schemas (`tools.py:313,393,425`).
- `CorpusKind`/`ChunkRole` Literals redefined in `app/rag/retriever.py:35`, `app/rag/ingest.py:21-22`, and `app/core/embed_providers/types.py`.

### R-07 ✅ Resolved as audit noise — no orchestration-cluster import cycle
**Original claim:** cluster `llm ↔ client_intents ↔ tools ↔ tool_router ↔ response_formatter ↔ llm_router ↔ model_registry` is a circular-import tangle held by ~30 in-function imports; lifting them causes startup ImportError.

**Current fact (2026-07-14):** that cluster is a **DAG** at import time. Lifting all peer deferred imports among those modules still yields **no SCCs**. Deferred imports remain (optional/heavy deps, historical style). Soft cycles that still need care (TYPE_CHECKING + lazy counterpart): `retriever` ↔ `reranker`, `tool_router` ↔ `routing_observability`. R-10 (`metrics` ← `main`) was fixed in T-035 (`app.core.health`). Do not treat “never lift any in-function import” as an absolute; verify with `python -c "import main"` after lifts.

### R-08 ⚠️⚠️ Oversized multi-responsibility files
- `app/rag/retriever.py` (912): models + global index state + ingestion orchestration + retrieval API + citation formatting + ranking math + cache I/O + tokenizer (~7 concerns).
- `app/core/tool_router.py` (834): result types + 2 backends + rerank + lifecycle/probes + 3 top-N functions + degradation reporting.
- `app/core/tools.py` (736): schemas + preview rendering + confirmation sanitizing + client-id resolution + execute dispatcher.
- `app/core/client_intents.py` (704): ~30 regexes + detectors + router-action dispatch + query path.
- `app/core/llm.py` (652): guardrails A/B/C/E + JSON sanitizing + orchestration + agentic loop + user-facing copy.
None fit comfortably in an 8B context window alongside a task prompt.

### R-09 ⚠️⚠️ Two stores, one SQLite file, divergent disciplines
`MemoryStore` uses versioned migrations via `PRAGMA user_version` (`app/memory/store.py:92-135`) and sets `foreign_keys=ON`, `busy_timeout=5000`, WAL (`store.py:106-120`). `KnowledgeStore` uses bare `CREATE TABLE IF NOT EXISTS` (`app/knowledge/store.py:30,44,61`) and sets only `foreign_keys=ON` (`store.py:20-24`). Schema changes to existing knowledge tables have **no migration path**; PRAGMA divergence is a latent concurrency inconsistency.

### R-10 ✅ Resolved — metrics no longer imports from `main`
Formerly `metrics.py` imported `_layer_availability` from `main`. **T-035** moved health probes to `app/core/health.py`; `metrics.py` imports `layer_availability` from there. Do not reintroduce `app/` → `main` imports.

### R-11 ⚠️⚠️ Private (underscored) names imported across modules
Partial fix **T-037**: public `tokenize` / `tf_cosine` in `retriever.py`; `tool_router` / `intent_kb` use those. Remaining cross-module `_`-imports (e.g. `_truncate_words`, `_resolve_client_id`, `_pii_preserved`) are still a footgun for AI "cleanup".

### R-12 ⚠️⚠️ Same name, different semantics
`_tokenize` exists 3×: `app/rag/retriever.py` (regex+lowercase), `app/rag/ingest.py` (whitespace split), and `intent_kb` imports retriever's. WebVTT timestamp formatting exists 3× (`app/knowledge/jobs.py`, `scripts/seed_youtube_channel.py`, `app/rag/transcript.py` — the last with different HH:MM:SS semantics). `chunk_text` vs `_chunk_token_window` near-duplicates in `app/rag/ingest.py`.

### R-13 ⚠️ Suspected dead / write-only code
- `embed_collection_chunks` removed in **T-036** (U-02).
- SQLite `knowledge_chunks` still write-mostly; retrieval uses in-memory indices (U-03).
- Legacy parallel APIs: `execute_tool` vs `execute_tool_outcome`; legacy `_index` / `_embedding_index_ready` aliases; deprecated env aliases in `config.py`.

### R-14 ⚠️⚠️ Weak static gates exactly where risk is highest
mypy `ignore_errors = true` for `app.core.tools`, `app.rag.retriever`, `app.core.tool_router`, `app.api.chat`, `app.api.openai_compat` (`pyproject.toml`) — hot files. (`model_registry` un-ignored in T-040.) Ruff runs `E,F` only with `E501` ignored.

### R-15 ⚠️⚠️⚠️ Rigid, undocumented wire formats
`/v1/chat/completions` must return the exact OpenAI envelope incl. `usage` with sentinel `-1` counts; streaming must emit `data: {chunk}\n\n` frames, final `finish_reason="stop"`, literal `data: [DONE]\n\n`. Streaming is faked (full reply generated, sliced into 6-char chunks); persistence + summary scheduling happen **inside** the stream generator; LLM failures are returned as normal-looking content, not HTTP errors. See `docs/WIRE_FORMATS.md` (T-014) for the documented contract.

### R-16 ⚠️ Module-level process state (narrowed 2026-07-14)
Distinguish **intentional single-process design** from the **RAG concurrency defect**:

**Accepted under single-tenant + `--workers 1` (not multi-tenant debt):**
- Process singletons/caches: tool-router backends (build locked), model/embed/rerank probes, httpx pool, metrics/routing counters, `confirmations._pending_writes` keyed by preview text (U-01 answered: one coach per instance), `openai_compat._MODEL_ID`.
- In-memory RAG index **as process state** (scale out via container replicas with separate memory, not in-process workers).

**Fixed — RAG generation consistency (was the real U-04 defect):**
- Former in-place `list.clear()` / `.append()` during reindex could mix generations in one retrieve when overlapped with `asyncio.to_thread` scoring (observable mode: mixed `chunk_id` gens, not reliable RuntimeError).
- Now: copy-on-write `_publish_index` + `_snapshot_index` under `_index_lock`; score outside the lock. Tests: `RagIndexConcurrencyTests` in `tests/test_concurrency.py`.

**Documented, not refactored (no concrete production impact forcing change):**
- Import-time `MemoryStore` / `SessionManager` (`chat.py`) and `KnowledgeStore` (`collections.py`) — tests redirect `MEMORY_DB_PATH` in `conftest` before import; lifestyle preference for lazy init, not a live bug under workers=1.
- `chat.reset_runtime_state()` wipes DB + pending writes — **test helper**; safe if unused in request paths (grep: tests only). Do not call from production handlers.

Embed probe cache lives in `app/core/health.py` (T-035), not `main.py`.

### R-17 ⚠️ Partial — process docs landed in roadmap Phase 1
`CLAUDE.md`, `CONVENTIONS.md`, `CONTRACTS.md`, `MODULE_MAP.md`, `WIRE_FORMATS.md`, `CONFIG.md`, `DEVELOPMENT.md`, and ADR-0012 process now exist. Remaining friction: some narrative docs still lag code; conventions that live mainly in code (`_with_meta` twins, emoji status markers, guardrail A/B/C/E, three meanings of “router”) still need care when editing hot paths.

### R-18 ⚠️⚠️ Test-harness traps
- Running via `unittest discover` skips `tests/conftest.py` (which sets `DEBUG=true` and redirects `MEMORY_DB_PATH`, `conftest.py:16-30`) → auth fails closed, real DB touched. Warned only in `docs/OPERATIONS.md:135`.
- CI pins `RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false`; defaults differ in production (formatter on). Without the pins, pytest hangs waiting on Ollama.
- Framework mix: mostly `unittest.TestCase`, some bare-pytest classes; no pytest marks — live tests gate via env flags (`RUN_RERANK_INTEGRATION=1`).

### R-19 ⚠️ Tracked junk files
`Untitled` (stray text: `MAX_TOKENS_FORMATTER`) and `c -l` (a Python script accidentally named after a shell command) are committed to git.

### R-20 ⚠️ Config coupling quirks
`TOOL_ROUTER_USE_E5_PREFIX` (a tool-router-named setting) is read by embed providers (`embed_providers/__init__.py:38`, `embed_providers/ollama.py:35`). Two rerank config namespaces (`rag_rerank_*` vs `tool_router_rerank_*`) drive one physical model. `rag_backend` values `"auto"` and `"embedding"` behave identically (`retriever.py:709-714`). `_MODEL_ID` bound at import (`openai_compat.py:61`).

---

## 3. Unknowns (verify — never assume)

| ID | Unknown | Status (2026-07-14) |
|----|---------|---------------------|
| U-01 | Is deployment single-tenant? (severity of global `_pending_writes`) | **Resolved:** single-tenant per instance (one API key, one SQLite CRM, `--workers 1`). Do not implement multi-tenancy without a product decision. |
| U-02 | Does anything call `embed_collection_chunks`? | **Resolved (T-036):** no callers; function removed. |
| U-03 | Is SQLite `knowledge_chunks` ever read back for retrieval? | **Resolved (T-036):** COUNT-only; retrieval uses in-memory indices. |
| U-04 | Can concurrent requests mutate/read unlocked module indices? | **Resolved:** workers=1 by design; RAG in-place race fixed via copy-on-write publish + snapshot (`retriever.py`); see `tests/test_concurrency.py`. |
| U-05 | Does the suite currently pass and meet the 75% floor? | **Resolved:** offline Test Execution Contract (ADR-0014) — suite green under pinned token backends. |
| U-06 | Do pyproject `[dependency-groups]` and `requirements*.txt` agree? | **Resolved as non-debt:** intentional dual SoT; requirements authoritative for CI/Docker; overlapping floors match. |

---

## 4. Facts small models get wrong without this file

1. Routing corpus = 363 examples today; count it, never quote a doc.
2. There are **9** chat tools, not 5; the authoritative list is `TOOL_DEFINITIONS` in `app/core/tools.py`.
3. Guardrails are A, B, C, **E** (no D); E = `_notes_grounded` in `app/core/llm.py`.
4. CI runs Python **3.12** with token backends and the formatter **disabled** — same version as local `.python-version` / Docker.
5. CI installs `requirements-dev.txt`, not pyproject dependency groups.
6. Tests must run via **pytest**, never `unittest discover`.
7. The mypy-clean status of `tools/model_registry/retriever/tool_router/chat/openai_compat` is an illusion: those modules are `ignore_errors = true`.
8. Streaming is simulated; there is no token-by-token generation path.
9. RAG indices are in-memory and rebuilt at startup; only embedding vectors are cached on disk.
10. `data/` holds app data (tool cards, eval sets, knowledge); `docs/` holds documentation only.
