# T-020 — scripts/check_contracts.py + CI step

**Phase:** 2 · **Complexity:** M · **Estimated session:** ~900 lines input; one new ~150-line script + 3-line CI diff
**Risks addressed:** R-05, R-06

## Goal
CI fails when a registered cross-file contract drifts: a magic string that no longer matches across its sites, or a tool-name list out of sync with `TOOL_DEFINITIONS`.

## Why this task exists
CONTRACTS.md (T-012) documents the must-match values, but documentation cannot stop a model from editing one site of a pair. A deterministic checker turns silent breakage into a red CI run (R-05, R-06).

## Context required
- `docs/roadmap/README.md` §1
- this file
- `docs/CONTRACTS.md` (from T-012) — the list of contracts to encode
- `.github/workflows/tests.yml` (~46 lines)
- For import-based checks: signatures only — `app/core/tools.py` `TOOL_DEFINITIONS`/`_WRITE_TOOLS`/`_VALID_NOTE_TYPES`; `app/core/llm_router.py` `_KNOWN_TOOLS`/`_ROUTER_SCHEMA`; `app/core/response_formatter.py` `_DATA_REPLY_PREFIX`.

## Files allowed to change
- `scripts/check_contracts.py` (create)
- `.github/workflows/tests.yml` (add one step)
- `docs/CONTRACTS.md` (update the header note to say the checker exists)

## Files forbidden to change
Everything else — the checker must ADAPT to current code, never the reverse. If a contract already fails, STOP and mark BLOCKED (a real drift exists).

## Dependencies
T-012.

## Preconditions
```bash
test -f docs/CONTRACTS.md && echo OK
test ! -f scripts/check_contracts.py && echo OK
```

## Steps
1. Write `scripts/check_contracts.py` (stdlib only; pattern for `sys.path` bootstrap: copy the header of `scripts/eval_tool_routing.py`). Checks, each printing PASS/FAIL:
   - `_DATA_REPLY_PREFIX` (import from `app.core.response_formatter`) is byte-identical to the literal used in `app/core/llm.py` (read the file, extract the string next to `_format_direct_lookup_reply`; simplest robust check: assert the literal `"Here are the details on file:"` occurs in both files).
   - Literals `"No notes on file."`, `"Registered clients:"`, `"pending confirmation"` each occur in BOTH their producer and consumer files (per CONTRACTS.md table).
   - `set(_KNOWN_TOOLS) == {d["name"] for d in TOOL_DEFINITIONS}` (via import) and the `_ROUTER_SCHEMA` enum equals the same set; `_WRITE_TOOLS ⊆` the set.
   - `_VALID_NOTE_TYPES` equals every inline note-type enum in the tool schemas (via import of `TOOL_DEFINITIONS`).
   - Every tool name has a card file in `data/tool-knowledge/` (warn-only, not fail: card naming may not be 1:1 — verify actual naming before deciding; if not verifiable, print WARN).
   - Exit 0 iff all non-warn checks pass.
2. Run it; all checks must pass against current code. A failure means either your check is wrong (fix the check) or a real drift exists (STOP, BLOCKED).
3. Add a CI step after ruff: `python scripts/check_contracts.py` (no special env needed — imports must not trigger network; verify by running with `OLLAMA_BASE_URL=http://127.0.0.1:1` unset network access, i.e. the script must finish instantly offline).
4. Update the CONTRACTS.md header. Commit `T-020: Add contract drift checker to CI`.

## Acceptance criteria
- `python3 scripts/check_contracts.py` exits 0 on a clean tree.
- Mutating one site of any registered pair (try locally, then revert) makes it exit non-zero.
- CI workflow contains the step.

## Required tests
The script is itself the test; the mutate-and-revert check above is mandatory and its result recorded in STATUS.md notes.

## Validation (run exactly)
```bash
python3 scripts/check_contracts.py && echo CONTRACTS-OK
.venv/bin/ruff check .
.venv/bin/python -m mypy app/
RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false \
  .venv/bin/python -m pytest tests/ -q
```

## Documentation updates
CONTRACTS.md header note.

## ADR impact
None.

## Definition of Done
Acceptance criteria met; validation passes; single commit; STATUS.md updated.

## Rollback plan
`git revert <commit>` — removes script + CI step; no runtime code touched.
