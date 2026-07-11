# T-012 — Create docs/CONTRACTS.md (must-match registry)

**Phase:** 1 · **Complexity:** M · **Estimated session:** ~700 lines input; one new ~120-line file
**Risks addressed:** R-05, R-06

## Goal
Every cross-file value that must stay synchronized (magic strings, tool-name lists, enums) is registered in one document with all its locations.

## Why this task exists
Control flow keys off exact string matches defined in multiple files (R-05), and the 9 tool names live in four hand-maintained lists (R-06). A model editing one site cannot know the others exist. This registry is also the spec for the automated checker (T-020) and the refactors (T-030, T-031).

## Context required
- `docs/roadmap/README.md` §1
- this file — the tables below ARE the draft content; your job is to verify each row and write the doc
- `docs/roadmap/REPO_AUDIT.md` — R-05, R-06 entries

## Files allowed to change
- `docs/CONTRACTS.md` (create)

## Files forbidden to change
Everything else. Do NOT centralize the strings in code — that is T-030/T-031.

## Dependencies
None.

## Preconditions (verify every row before writing it)
```bash
grep -n "Here are the details on file" app/core/llm.py app/core/response_formatter.py   # 1 hit each
grep -n "No notes on file." app/core/tools.py app/core/llm.py                            # producer + matcher
grep -n "Registered clients:" app/core/tools.py app/core/response_formatter.py           # producer + 2 matchers
grep -rn "pending confirmation" app/core/tools.py app/core/confirmations.py | head       # producers + matcher
grep -n "_KNOWN_TOOLS" app/core/llm_router.py                                            # hand list
grep -n "_WRITE_TOOLS\|_VALID_NOTE_TYPES" app/core/tools.py                              # hand lists
```
If a grep returns nothing, that row has drifted: record in STATUS.md, omit the row, continue.

## Steps
Create `docs/CONTRACTS.md` with three tables, each row = (value → every location, `file:line`, producer/consumer role, what breaks on drift):
1. **Magic strings:** `"Here are the details on file:\n\n"`; `"No notes on file."`; `"Registered clients:"`; `"pending confirmation"`; emoji markers ⏳/✅/❌.
2. **Tool names (9):** locations `tools.TOOL_DEFINITIONS`, `tools._WRITE_TOOLS`, `llm_router._KNOWN_TOOLS`, `llm_router._ROUTER_SCHEMA` enum — plus the non-code locations: tool cards in `data/tool-knowledge/*.md` and routing examples in `data/tool-knowledge/examples/routing.jsonl`.
3. **Other enums:** note types `{general,story,decision,goal,progress}` (`tools._VALID_NOTE_TYPES` + inline schema enums at `tools.py:313,393,425`); `CorpusKind`/`ChunkRole` Literals (`app/rag/retriever.py:35`, `app/rag/ingest.py:21-22`, `app/core/embed_providers/types.py`).
Header rule for the doc: *"Before changing any value in this file's tables, update every listed location in the same commit, then run `scripts/check_contracts.py` (once T-020 lands)."*

## Acceptance criteria
- All three tables present; every `file:line` verified this session; drifted rows recorded in STATUS.md instead of guessed.

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
None.

## Definition of Done
Acceptance criteria met; validation passes; single commit `T-012: Create docs/CONTRACTS.md`; STATUS.md updated.

## Rollback plan
`git revert <commit>` — new file only.
