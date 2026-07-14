# T-004 — Correct stale facts in ARCHITECTURE.md

**Phase:** 0 · **Complexity:** S · **Estimated session:** ~400 lines input; small docs diff
**Risks addressed:** R-01

## Goal
`docs/ARCHITECTURE.md` contains no claims contradicted by the repository.

## Why this task exists
ARCHITECTURE.md is the document future models will read first. It currently states a wrong corpus location, a wrong corpus size (twice, two different wrong numbers), and misfiles a module (R-01). False statements in the primary architecture doc are directly copied into future code and docs.

## Context required
- `docs/roadmap/README.md` §1
- this file
- `docs/ARCHITECTURE.md` (entire file, ~254 lines)

## Files allowed to change
- `docs/ARCHITECTURE.md`

## Files forbidden to change
Everything else — especially do NOT "fix" other docs in this task (they have their own tasks) and do NOT touch any `.py` file.

## Dependencies
None.

## Preconditions (verify before editing)
```bash
grep -n "130" docs/ARCHITECTURE.md                          # hits near lines 110 and 215 (corpus size claims)
grep -n "docs/tool-knowledge\|tool-knowledge/" docs/ARCHITECTURE.md   # a file-map entry places tool-knowledge under docs/ (~line 214-220)
grep -n "knowledge_paths" docs/ARCHITECTURE.md              # listed under app/rag/ (~line 37)
test -d data/tool-knowledge && echo OK                      # OK
test -f app/core/knowledge_paths.py && echo OK              # OK
wc -l data/tool-knowledge/examples/routing.jsonl            # note the real count (was 363 on 2026-07-10)
```

## Steps
1. Replace every corpus-size number ("130 examples", "307 examples") with the phrase: `363+ examples (authoritative count: wc -l data/tool-knowledge/examples/routing.jsonl)` using the count you measured.
2. Fix the file map so `tool-knowledge/` appears under `data/`, not `docs/`.
3. Move the `knowledge_paths.py` entry from the `app/rag/` section to the `app/core/` section.
4. Read the surrounding sections you touched; if you notice another claim that a one-command check disproves, fix it ONLY if the check is in this file's spirit (path exists / count matches). Otherwise add it to STATUS.md Notes.
5. Validation, commit `T-004: Correct stale facts in ARCHITECTURE.md`.

## Acceptance criteria
- `grep -n "307\|130 examples" docs/ARCHITECTURE.md` → no corpus-size hits.
- `grep -n "docs/tool-knowledge" docs/ARCHITECTURE.md` → no hits.
- `knowledge_paths.py` listed under `app/core/`.

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
This task IS the documentation update.

## ADR impact
None.

## Definition of Done
Acceptance criteria met; validation passes; single commit; STATUS.md updated.

## Rollback plan
`git revert <commit>` — docs-only.
