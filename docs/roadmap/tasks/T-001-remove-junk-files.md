# T-001 — Remove tracked junk files

**Phase:** 0 · **Complexity:** S · **Estimated session:** < 100 lines input; 2-file deletion diff
**Risks addressed:** R-19

## Goal
The accidentally committed files `Untitled` and `c -l` no longer exist in the repository.

## Why this task exists
Junk files confuse file discovery: a model globbing the repo root will read `c -l` (a stray Python script) and may treat it as live code, or invent meaning for `Untitled` (R-19).

## Context required
- `docs/roadmap/README.md` §1 (protocol)
- this file

## Files allowed to change
- `Untitled` (delete)
- `c -l` (delete)

## Files forbidden to change
Everything else. Do NOT add `.gitignore` entries (these are tracked files, not ignore candidates). Do NOT delete `artifacts/` or `graphify-out/` — they are untracked local dirs, out of scope.

## Dependencies
None.

## Preconditions (verify before editing)
```bash
git ls-files | grep -x "Untitled"        # prints: Untitled
git ls-files | grep -x "c -l"            # prints: c -l
git grep -l "c -l" -- "*.py" "*.md" "*.toml" "*.yml" | grep -v roadmap   # no output (nothing references them)
```
If any check fails: STOP, mark BLOCKED in STATUS.md.

## Steps
1. `git rm "Untitled" "c -l"`
2. Run validation.
3. Commit as `T-001: Remove tracked junk files`.

## Acceptance criteria
- `git ls-files | grep -E "^(Untitled|c -l)$"` prints nothing.
- Diff contains exactly two deletions and the STATUS.md row update.

## Required tests
None (no code change). Standard validation block still required.

## Validation (run exactly)
```bash
.venv/bin/ruff check .
.venv/bin/python -m mypy app/
RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false \
  .venv/bin/python -m pytest tests/ -q
```

## Documentation updates
None.

## ADR impact
None.

## Definition of Done
- Acceptance criteria met; validation passes.
- Single commit `T-001: Remove tracked junk files`; STATUS.md updated in same commit.

## Rollback plan
`git revert <commit>` — pure file deletion, no runtime dependency on these files (verified by the grep precondition).
