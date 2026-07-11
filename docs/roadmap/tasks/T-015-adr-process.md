# T-015 — ADR-0012: define the ADR process

**Phase:** 1 · **Complexity:** S · **Estimated session:** ~200 lines input; one new ADR + README update
**Risks addressed:** R-17

## Goal
`docs/adr/` defines when an ADR is required, how numbers are assigned, and how supersession is marked.

## Why this task exists
The ADR README has a template but no process (R-17). Without a rule, models either skip ADRs for architecture changes or write them for trivia; supersession is currently ad-hoc prose in Status lines.

## Context required
- `docs/roadmap/README.md` §1
- this file
- `docs/adr/README.md` (~45 lines)

## Files allowed to change
- `docs/adr/0012-adr-process.md` (create)
- `docs/adr/README.md` (add index row + link process section)

## Files forbidden to change
Everything else, including all existing ADRs.

## Dependencies
None.

## Preconditions
```bash
ls docs/adr/ | grep -c '^00'          # 11 ADR files (0001-0011); 0012 free
test ! -f docs/adr/0012-adr-process.md && echo OK
```

## Steps
1. Write ADR-0012 using the existing template, deciding:
   - **When required:** any change to module boundaries, storage schema mechanics, provider/backends, wire formats, or cross-file contracts (the CONTRACTS.md registry). Not required for bug fixes, docs, or single-module refactors.
   - **Numbering:** next free 4-digit number; check `ls docs/adr/` first; never renumber.
   - **Supersession:** old ADR gets `**Status:** Superseded by ADR-xxxx` (keep body); new ADR names what it supersedes in Context.
   - **Format:** Date (real), Status, Context, Decision, Consequences — per the template already in README.
2. Add ADR-0012 to the index table in `docs/adr/README.md` and a short "Process" section linking to it.
3. Validation, commit `T-015: ADR-0012 define the ADR process`.

## Acceptance criteria
- ADR-0012 exists, follows the template, Status Accepted, real date.
- README index lists 12 ADRs.

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
Creates ADR-0012.

## Definition of Done
Acceptance criteria met; validation passes; single commit; STATUS.md updated.

## Rollback plan
`git revert <commit>` — new file + index row.
