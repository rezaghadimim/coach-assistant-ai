# T-013 — Create docs/MODULE_MAP.md (layering + import rules)

**Phase:** 1 · **Complexity:** M · **Estimated session:** ~900 lines input; one new ~150-line file
**Risks addressed:** R-07, R-10, R-11, R-16

## Goal
One document states, per module: what it owns, what it may import, its module-level state, and its import-time side effects — so a model never has to infer architecture.

## Why this task exists
The orchestration cluster is a circular-import tangle held together by ~30 in-function imports (R-07); `metrics.py` imports from `main` (R-10); private names are imported cross-module (R-11); several modules have import-time side effects (R-16). None of this is written down; a model that moves an import or adds a module-level singleton breaks startup in ways tests may not catch.

## Context required
- `docs/roadmap/README.md` §1
- this file — the content outline below carries the verified facts; spot-check the citations you use
- `docs/roadmap/REPO_AUDIT.md` — R-07, R-10, R-11, R-16 entries (contain all file:line evidence)

## Files allowed to change
- `docs/MODULE_MAP.md` (create)

## Files forbidden to change
Everything else. Do NOT fix any import or move any code — documentation only.

## Dependencies
None.

## Preconditions
```bash
test ! -f docs/MODULE_MAP.md && echo OK
grep -n "from main import\|import main" app/api/metrics.py   # reverse import exists (~line 124)
```

## Steps
Create `docs/MODULE_MAP.md` with four sections:
1. **Ownership table** — one row per module in `app/` (api, core, rag, knowledge, memory, models, training): one-line responsibility. Source: REPO_AUDIT.md §1 plus a directory listing.
2. **Layering diagram + import rules** — `api → core → (rag | knowledge | memory)`; `models` and `config`/`observability` importable from anywhere; **rules:** (a) core must not import from api; (b) the one known violation is `app/api/metrics.py:124` importing `_layer_availability` from `main` (fix scheduled: T-035) — do not add more; (c) in-function imports inside the cluster `llm ↔ client_intents ↔ tools ↔ tool_router ↔ response_formatter ↔ llm_router ↔ model_registry` are deliberate cycle-breaks — never lift one to module level without running the app (`python3 -c "import main"`); (d) never import `_underscored` names across modules (existing violations listed with pointer to T-037).
3. **Module-level state registry** — table of every known singleton/global/cache with location: retriever indices + readiness flags, `confirmations._pending_writes`, `tool_router` backend state, `model_registry._probe_cache`, `rerank._encoder`/`_probe_ok`, `llm_providers/http._clients`, `routing_observability` counters, `metrics` counters, `chat._sessions`, `chat` store/session_manager singletons, `collections.py` KnowledgeStore, `main._embed_probe_cache`, `openai_compat._MODEL_ID`. (All locations are in REPO_AUDIT.md R-16.)
4. **Import-time side effects** — `chat.py:34-35` (DB + migrations run at import), `collections.py:27`, `rerank.py:27` (`HF_HUB_DISABLE_XET` must be set before huggingface_hub loads), `intent_kb.py:196-197` (vector precompute). Rule: adding import-time work requires maintainer sign-off.

## Acceptance criteria
- Four sections present; each cited location spot-verified; no prescriptive refactoring beyond pointers to existing tasks.

## Required tests
None (docs-only). Standard validation block still required.

## Validation (run exactly)
```bash
.venv/bin/ruff check .
.venv/bin/python -m mypy app/
RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false \
  .venv/bin/python -m pytest tests/ -q
```

## Documentation updates
This task IS documentation.

## ADR impact
None.

## Definition of Done
Acceptance criteria met; validation passes; single commit `T-013: Create docs/MODULE_MAP.md`; STATUS.md updated.

## Rollback plan
`git revert <commit>` — new file only.
