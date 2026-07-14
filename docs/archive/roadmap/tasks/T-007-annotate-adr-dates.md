# T-007 — Annotate backfilled ADR dates

**Phase:** 0 · **Complexity:** S · **Estimated session:** ~300 lines input; 5 one-line diffs
**Risks addressed:** R-02

## Goal
ADRs 0001–0005 no longer present the placeholder date `2024-01-01` as a real decision date.

## Why this task exists
ADRs 0001–0005 are dated `2024-01-01` while real ADR activity starts 2026-06 (ADRs 0006–0011). A model reconstructing project history will misdate decisions and may treat old ADRs as long-settled when they are recent backfills (R-02).

## Context required
- `docs/roadmap/README.md` §1
- this file
- `docs/adr/0001-*.md` … `docs/adr/0005-*.md` — the `**Date:**` line of each only

## Files allowed to change
- `docs/adr/0001-local-llm-with-ollama.md`
- `docs/adr/0002-fastapi-web-framework.md`
- `docs/adr/0003-in-memory-rag-retrieval.md`
- `docs/adr/0004-sqlite-memory-persistence.md`
- `docs/adr/0005-openwebui-integration.md`

## Files forbidden to change
Everything else — do NOT edit ADR content/decisions, do NOT renumber, do NOT touch ADRs 0006+ or `docs/adr/README.md`.

## Dependencies
None.

## Preconditions (verify before editing)
```bash
grep -l "2024-01-01" docs/adr/*.md | wc -l    # 5
```

## Steps
1. In each of the five files, change `**Date:** 2024-01-01` to `**Date:** 2024-01-01 (backfilled placeholder — written retroactively; see ADR-0006 onward for dated records)`.
2. Validation, commit `T-007: Annotate backfilled ADR dates`.

## Acceptance criteria
- All five ADRs carry the backfilled annotation; no other lines changed.

## Required tests
None (docs-only). Standard validation block still required.

## Validation (run exactly)
```bash
grep -c "backfilled placeholder" docs/adr/*.md | grep -v ":0" | wc -l   # 5
.venv/bin/ruff check .
.venv/bin/python -m mypy app/
RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false \
  .venv/bin/python -m pytest tests/ -q
```

## Documentation updates
This task IS the documentation update.

## ADR impact
Annotates ADR-0001…0005 metadata; decisions unchanged.

## Definition of Done
Acceptance criteria met; validation passes; single commit; STATUS.md updated.

## Rollback plan
`git revert <commit>` — docs-only.
