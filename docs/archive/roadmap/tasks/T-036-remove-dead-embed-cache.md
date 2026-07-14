# T-036 — Resolve U-02/U-03: dead `embed_collection_chunks` + write-only chunks table

**Phase:** 3 · **Complexity:** M · **Estimated session:** ~600 lines input; deletion diff OR docs-only outcome
**Risks addressed:** R-13 · **Resolves unknowns:** U-02, U-03

## Goal
Either `embed_collection_chunks` is confirmed dead and removed (taking its divergent second cache format with it), or it is confirmed live and documented. Same for the read-back status of the `knowledge_chunks` SQLite table. No guessing — this task's first half is pure investigation.

## Why this task exists
`app/knowledge/ingest.py:embed_collection_chunks` (~lines 239–287) writes a header-less embedding cache with hand-duplicated key logic, apparently uncalled (R-13/U-02); `knowledge_chunks` rows appear write-only (U-03). Dead code with a *plausible name* is prime hallucination bait — a future model will call it and corrupt the real cache format.

## Context required
- `docs/roadmap/README.md` §1
- this file
- `app/knowledge/ingest.py` (entire file, ~287 lines)
- Grep results gathered in Steps (do not pre-read more files)

## Files allowed to change
- `app/knowledge/ingest.py` (deletion only, if confirmed dead)
- `app/knowledge/store.py` (docstring/comment only)
- `docs/RAG.md` (one clarifying paragraph)
- `docs/roadmap/STATUS.md` (U-02/U-03 resolution)

## Files forbidden to change
- `app/rag/retriever.py` and its cache format — untouched regardless of outcome.
- Everything else.

## Dependencies
T-013.

## Preconditions / Investigation (the outcome branches on these)
```bash
grep -rn "embed_collection_chunks" app/ scripts/ tests/        # record every hit
grep -rn "knowledge_chunks" app/ scripts/ tests/               # record every hit; classify each as WRITE or READ
```

## Steps
**Branch A — no caller of `embed_collection_chunks` outside its definition:**
1. Delete the function and any now-unused imports/helpers it exclusively used (e.g. its inline sha256 key logic).
2. Confirm no test breaks; if a test imports it, the test is the only caller → delete that test too and note it.

**Branch B — a caller exists:** do NOT delete. Document in `docs/RAG.md`: who calls it, and the fact that it writes a second cache format (list both formats' paths).

**knowledge_chunks (both branches):**
3. Classify each grep hit. If no code reads rows back (only writes/counts), add a comment above the table DDL in `app/knowledge/store.py`: `NOTE: rows are written at ingest but retrieval reads only the in-memory index (app/rag/retriever.py); this table is bookkeeping/inspection only.` If a real reader exists, document that instead.
4. Add one paragraph to `docs/RAG.md` stating where retrieval actually reads from (in-memory index) and what the SQLite chunks are for.
5. Update STATUS.md unknowns table (U-02, U-03 → Resolved, with the answer).
6. Validation, commit `T-036: Resolve dead embed cache / write-only chunks (U-02, U-03)`.

## Acceptance criteria
- U-02 and U-03 rows in STATUS.md are Resolved with evidence (the grep hit lists).
- Branch A: `grep -rn "embed_collection_chunks" app/ scripts/ tests/` → 0 hits; suite green.
- Branch B: function untouched; documentation added.

## Required tests
No new tests. Full regression suite (deletion safety).

## Validation (run exactly)
```bash
.venv/bin/ruff check .
.venv/bin/python -m mypy app/
RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false \
  .venv/bin/python -m pytest tests/ -q
```

## Documentation updates
docs/RAG.md paragraph; store.py comment.

## ADR impact
None.

## Definition of Done
Acceptance criteria met; validation passes; single commit; STATUS.md updated (incl. unknowns table).

## Rollback plan
`git revert <commit>`. Branch A deletes code with zero callers (proven by grep + green suite), so revert is only needed if the grep missed a dynamic call — note: also grep for the string in quotes (`"embed_collection_chunks"`) to catch reflection before deleting.
