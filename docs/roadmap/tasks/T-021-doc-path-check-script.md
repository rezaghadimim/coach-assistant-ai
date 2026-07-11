# T-021 — scripts/check_doc_paths.py + CI step

**Phase:** 2 · **Complexity:** M · **Estimated session:** ~400 lines input; one new ~80-line script + CI step
**Risks addressed:** R-01, R-02

## Goal
CI fails when documentation references a repo path that does not exist, so path drift (the `docs/tool-knowledge` class of error) cannot recur.

## Why this task exists
The audit found several doc-cited paths that no longer exist (R-01, R-02). Docs are the primary input for small models; a dead path in a doc becomes a hallucinated path in code.

## Context required
- `docs/roadmap/README.md` §1
- this file
- `.github/workflows/tests.yml`

## Files allowed to change
- `scripts/check_doc_paths.py` (create)
- `.github/workflows/tests.yml` (add one step)
- Doc files ONLY where the checker finds a dead path (fix the path or remove the reference; each fix noted in STATUS.md)

## Files forbidden to change
Any `.py` under `app/`; any file under `data/`.

## Dependencies
T-004, T-005, T-006 (known stale docs already fixed, so the checker starts green-ish).

## Preconditions
```bash
test ! -f scripts/check_doc_paths.py && echo OK
grep -n "docs/tool-knowledge" docs/*.md | wc -l    # 0 (T-004 done)
```

## Steps
1. Write `scripts/check_doc_paths.py` (stdlib only): scan `README.md`, `CLAUDE.md` (if present), `docs/**/*.md` (excluding `docs/archive/` and `docs/roadmap/`), extract candidate repo paths via regex (markdown links to relative paths, and backtick-quoted strings matching `^(app|data|docs|scripts|tests)/[A-Za-z0-9_./-]+$`), and verify each exists (`Path.exists()`, after stripping `:line` suffixes and `#anchors`). Skip URLs, globs (`*`), and template placeholders (`<...>`). Print each missing path; exit non-zero if any.
2. Run it. Fix any dead references it finds in docs (smallest edit that makes the reference true). If a reference is ambiguous (you cannot tell what it should point to), leave it, add it to an allowlist constant `KNOWN_UNRESOLVED` in the script with a comment, and record it in STATUS.md as Unknown.
3. Add CI step after the contracts check: `python scripts/check_doc_paths.py`.
4. Commit `T-021: Add doc path checker to CI`.

## Acceptance criteria
- `python3 scripts/check_doc_paths.py` exits 0.
- Temporarily adding a fake path to a doc (then reverting) makes it exit non-zero.
- `KNOWN_UNRESOLVED` is empty or each entry has a comment + STATUS.md note.

## Required tests
The mutate-and-revert check above; result recorded in STATUS.md.

## Validation (run exactly)
```bash
python3 scripts/check_doc_paths.py && echo DOCPATHS-OK
.venv/bin/ruff check .
.venv/bin/python -m mypy app/
RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false \
  .venv/bin/python -m pytest tests/ -q
```

## Documentation updates
Only dead-path fixes surfaced by the checker.

## ADR impact
None.

## Definition of Done
Acceptance criteria met; validation passes; single commit; STATUS.md updated.

## Rollback plan
`git revert <commit>`.
