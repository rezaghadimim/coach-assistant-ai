# T-003 — Fix stale doc pointer in pyproject.toml

**Phase:** 0 · **Complexity:** S · **Estimated session:** < 100 lines input; 1-line diff
**Risks addressed:** R-02

## Goal
The mypy-override comment in `pyproject.toml` points to the real location of the production-readiness checklist.

## Why this task exists
`pyproject.toml` (comment above `[[tool.mypy.overrides]]`, near line 65) references `docs/PRODUCTION_READINESS_CHECKLIST.md`, which was moved to `docs/archive/PRODUCTION_READINESS_CHECKLIST.md`. A model following the pointer fails to find it and may recreate the file or guess its content (R-02).

## Context required
- `docs/roadmap/README.md` §1
- this file
- `pyproject.toml` lines 50–80

## Files allowed to change
- `pyproject.toml` (the one comment line only)

## Files forbidden to change
Everything else. Do NOT move the checklist back out of `docs/archive/`. Do NOT change any mypy settings.

## Dependencies
None.

## Preconditions (verify before editing)
```bash
grep -n "docs/PRODUCTION_READINESS_CHECKLIST.md" pyproject.toml     # 1 hit
test -f docs/archive/PRODUCTION_READINESS_CHECKLIST.md && echo OK   # OK
```

## Steps
1. In the comment, replace `docs/PRODUCTION_READINESS_CHECKLIST.md` with `docs/archive/PRODUCTION_READINESS_CHECKLIST.md`.
2. Validation, commit `T-003: Fix stale doc pointer in pyproject.toml`.

## Acceptance criteria
- `grep -rn "docs/PRODUCTION_READINESS_CHECKLIST" pyproject.toml` shows only the `docs/archive/` path.
- Diff is exactly one comment line + STATUS.md.

## Required tests
None. Standard validation block still required.

## Validation (run exactly)
```bash
.venv/bin/ruff check .
.venv/bin/python -m mypy app/
RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false \
  .venv/bin/python -m pytest tests/ -q
```

## Documentation updates
None (the change is the documentation fix).

## ADR impact
None.

## Definition of Done
Acceptance criteria met; validation passes; single commit; STATUS.md updated.

## Rollback plan
`git revert <commit>` — comment-only change.
