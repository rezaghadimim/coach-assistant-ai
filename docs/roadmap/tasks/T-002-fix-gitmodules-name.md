# T-002 — Fix `.gitmodules` submodule name

**Phase:** 0 · **Complexity:** S · **Estimated session:** < 100 lines input; 1-line diff
**Risks addressed:** R-02

## Goal
The submodule section name in `.gitmodules` matches its path: `data/knowledge/private`.

## Why this task exists
`.gitmodules` currently reads `[submodule "docs/knowledge/private"]` with `path = data/knowledge/private` — a leftover from when knowledge lived under `docs/`. A model reading `.gitmodules` will conclude a `docs/knowledge/private` submodule exists and reference the wrong path (R-02).

## Context required
- `docs/roadmap/README.md` §1
- this file
- `.gitmodules` (entire file, 3 lines)

## Files allowed to change
- `.gitmodules`

## Files forbidden to change
Everything else. Do NOT run `git submodule deinit/init/sync --force` variants beyond the single `sync` in Steps. Do NOT touch `data/knowledge/private/` contents or the submodule pointer.

## Dependencies
None.

## Preconditions (verify before editing)
```bash
grep -n 'submodule "docs/knowledge/private"' .gitmodules   # 1 hit
grep -n 'path = data/knowledge/private' .gitmodules        # 1 hit
git submodule status                                       # one line, path data/knowledge/private, no leading - or +
```

## Steps
1. In `.gitmodules`, change the section header `[submodule "docs/knowledge/private"]` to `[submodule "data/knowledge/private"]`. Leave `path` and `url` untouched.
2. Run `git submodule sync -- data/knowledge/private` (updates local config to the renamed section).
3. Run `git submodule status` — output must be unchanged from the precondition (same sha, same path, no `-`/`+` prefix).
4. Validation, then commit `T-002: Fix .gitmodules submodule name`.

## Acceptance criteria
- `.gitmodules` section name equals the path.
- `git submodule status` shows the submodule still initialized at the same commit.

## Required tests
None. Standard validation block still required.

## Validation (run exactly)
```bash
git submodule status          # same sha as before, no - / + prefix
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
- Acceptance criteria met; validation passes; single commit; STATUS.md updated.

## Rollback plan
`git revert <commit>` then `git submodule sync`. The rename only affects config bookkeeping, not the checked-out submodule content.
