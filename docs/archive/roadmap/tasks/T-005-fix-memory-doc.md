# T-005 — Correct tool table in MEMORY.md

**Phase:** 0 · **Complexity:** S · **Estimated session:** ~900 lines input; small docs diff
**Risks addressed:** R-01

## Goal
`docs/MEMORY.md` lists all nine chat tools, matching `TOOL_DEFINITIONS` in `app/core/tools.py`.

## Why this task exists
MEMORY.md lists only 5 of the 9 tools (missing `get_client_full`, `update_client_note`, `delete_client_note`, `delete_client`). A model using MEMORY.md as the tool contract will not know update/delete exist and may reimplement them (R-01).

## Context required
- `docs/roadmap/README.md` §1
- this file
- `docs/MEMORY.md` (entire file, ~61 lines)
- `app/core/tools.py` — ONLY the `TOOL_DEFINITIONS` list (starts near line 237): read each tool's `name` and `description` fields. Do not read the rest of the file.

## Files allowed to change
- `docs/MEMORY.md`

## Files forbidden to change
Everything else, especially `app/core/tools.py`.

## Dependencies
None.

## Preconditions (verify before editing)
```bash
grep -c '"name"' app/core/tools.py    # count of name fields; expect ≥ 9
grep -n 'create_client\|add_client_note\|get_client\|list_client_notes\|list_clients' docs/MEMORY.md  # existing 5-row table (~lines 34-40)
```

## Steps
1. Extract the 9 tool names + one-line descriptions from `TOOL_DEFINITIONS`.
2. Rewrite the MEMORY.md tool table to list all 9, with a header note: `Authoritative source: TOOL_DEFINITIONS in app/core/tools.py — update this table when that list changes.`
3. Validation, commit `T-005: Correct tool table in MEMORY.md`.

## Acceptance criteria
- Every tool `name` in `TOOL_DEFINITIONS` appears in the MEMORY.md table, and no extra tools appear.
- The authoritative-source note is present.

## Required tests
None (docs-only). Standard validation block still required.

## Validation (run exactly)
```bash
for t in $(grep -o '"name": *"[a-z_]*"' app/core/tools.py | cut -d'"' -f4 | sort -u); do
  grep -q "$t" docs/MEMORY.md || echo "MISSING: $t"; done          # no output
.venv/bin/ruff check .
.venv/bin/python -m mypy app/
RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false \
  .venv/bin/python -m pytest tests/ -q
```

## Documentation updates
This task IS the documentation update.

## ADR impact
None.

## Definition of Done
Acceptance criteria met; validation passes; single commit; STATUS.md updated.

## Rollback plan
`git revert <commit>` — docs-only.
