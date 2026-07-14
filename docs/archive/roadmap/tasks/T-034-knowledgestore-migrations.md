# T-034 — KnowledgeStore: PRAGMA parity + versioned migrations

**Phase:** 3 · **Complexity:** M · **Estimated session:** ~800 lines input; store.py diff + tests
**Risks addressed:** R-09

## Goal
`KnowledgeStore` uses the same connection PRAGMAs as `MemoryStore` (WAL, busy_timeout, foreign_keys) and gains a versioned migration list, so future schema changes to knowledge tables have a defined path.

## Why this task exists
Two store classes share `data/coach_assistant.db` with divergent disciplines (R-09): KnowledgeStore has no migration mechanism (`CREATE TABLE IF NOT EXISTS` can never alter an existing table) and no WAL/busy_timeout (concurrency inconsistency). A model asked to "add a column to knowledge_sources" today has no correct way to do it.

## Context required
- `docs/roadmap/README.md` §1
- this file
- `app/memory/store.py` lines ~88–135 (the migration engine + PRAGMA pattern to copy) — note the comment at `store.py:110-118` explaining PRAGMA ordering
- `app/knowledge/store.py` (entire file, ~245 lines)
- `tests/test_migrations.py` (pattern for migration regression tests)

## Files allowed to change
- `app/knowledge/store.py`
- `tests/test_knowledge_jobs.py` OR a new `tests/test_knowledge_store_migrations.py` (prefer new file)

## Files forbidden to change
- `app/memory/store.py` (copy its pattern; do not refactor it or extract a shared base class — that is a bigger boundary change requiring an ADR)
- Everything else.

## Dependencies
T-013.

## Preconditions
```bash
grep -n "busy_timeout\|journal_mode" app/knowledge/store.py | wc -l   # 0 (PRAGMAs absent)
grep -n "user_version" app/knowledge/store.py | wc -l                 # 0 (no migrations)
grep -n "user_version" app/memory/store.py                            # engine exists to copy
```
**Caution:** both stores share one DB file and `PRAGMA user_version` is per-file — the version counter is ALREADY used by MemoryStore. The knowledge migration mechanism MUST NOT touch `user_version`. Use a dedicated table instead (see Steps).

## Steps
1. In `KnowledgeStore._connect`, mirror MemoryStore's PRAGMA sequence and ordering rationale: `foreign_keys=ON`, `busy_timeout=5000`, then `journal_mode=WAL` (copy the explanatory comment).
2. Add a migration mechanism that does NOT use `user_version` (owned by MemoryStore): create table `knowledge_schema_version(version INTEGER NOT NULL)` with a single row; an ordered `MIGRATIONS: list` module constant (append-only comment copied from `memory/store.py:88-91`); run pending migrations in one transaction at init, after the `CREATE TABLE IF NOT EXISTS` block. Migration list starts empty (version 0 = current schema).
3. New test file: (a) fresh DB initializes at version 0 with all three knowledge tables; (b) a dummy in-test migration appended to a copied list applies and bumps the version; (c) opening a DB created by the OLD code (simulate: create tables manually without the version table) upgrades cleanly to version 0; (d) `MemoryStore` + `KnowledgeStore` on the same tmp file coexist and `PRAGMA user_version` is untouched by KnowledgeStore.
4. Validation, commit `T-034: KnowledgeStore PRAGMA parity + versioned migrations`.

## Acceptance criteria
- PRAGMAs match MemoryStore's (same values, same order).
- `user_version` untouched by KnowledgeStore (test d proves it).
- Existing DBs open cleanly (test c).
- Full suite green.

## Required tests
The four tests in step 3; full regression suite.

## Validation (run exactly)
```bash
.venv/bin/ruff check .
.venv/bin/python -m mypy app/
RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false \
  .venv/bin/python -m pytest tests/ -q
```

## Documentation updates
docs/MEMORY.md: one paragraph noting knowledge tables now migrate via `knowledge_schema_version` (separate from `user_version`).

## ADR impact
Updates ADR-0004 (SQLite persistence): add a note that knowledge tables gained a versioned migration mechanism. One paragraph, Status unchanged.

## Definition of Done
Acceptance criteria met; validation passes; single commit; STATUS.md updated.

## Rollback plan
`git revert <commit>`. Safe: the only persistent artifact is the `knowledge_schema_version` table, which old code ignores (verify test c covers the reverse direction: old-code compatibility).
