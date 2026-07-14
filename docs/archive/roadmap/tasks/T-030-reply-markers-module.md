# T-030 — Centralize cross-file reply-marker strings

**Phase:** 3 · **Complexity:** M · **Estimated session:** ~1,000 lines input; ~40-line diff across 5 files
**Risks addressed:** R-05

## Goal
Each must-match string has exactly one definition, in a new dependency-free module `app/core/reply_markers.py`; all producers and consumers import it.

## Why this task exists
Control flow keys off exact string matches defined independently in multiple files (R-05). One definition site makes drift impossible instead of merely detected (T-020 keeps guarding the consumers' behavior).

## Context required
- `docs/roadmap/README.md` §1
- this file
- `docs/CONTRACTS.md` — magic-strings table (authoritative site list)
- The specific regions CONTRACTS.md cites in: `app/core/llm.py`, `app/core/response_formatter.py`, `app/core/tools.py`, `app/core/confirmations.py` (read ±20 lines around each cited line, not the whole files)

## Files allowed to change
- `app/core/reply_markers.py` (create)
- `app/core/llm.py`, `app/core/response_formatter.py`, `app/core/tools.py`, `app/core/confirmations.py` (only the lines using the registered strings)
- `tests/test_response_formatter.py` (add one test)
- `scripts/check_contracts.py`, `docs/CONTRACTS.md` (update site lists)

## Files forbidden to change
Everything else. Do NOT change any string's VALUE — byte-identical moves only. Do NOT touch the emoji markers (they stay in `tools.py`'s docstring convention; out of scope).

## Dependencies
T-012, T-020.

## Preconditions
```bash
python3 scripts/check_contracts.py && echo OK     # green before starting
grep -n "Here are the details on file" app/core/llm.py app/core/response_formatter.py   # both hits present
```

## Steps
1. Create `app/core/reply_markers.py`: module docstring ("single source of truth for reply strings matched across modules; see docs/CONTRACTS.md"), then constants copied byte-for-byte: `DATA_REPLY_PREFIX`, `NO_NOTES_REPLY`, `REGISTERED_CLIENTS_PREFIX`, `PENDING_CONFIRMATION_MARKER`. It must import nothing from `app.*` (it sits below every layer).
2. In each producer/consumer file, replace the literal with the imported constant (module-level import is safe — the new module has no dependencies, no cycle risk). Keep `response_formatter._DATA_REPLY_PREFIX` as an alias of the new constant (other code/tests may reference it).
3. Add a test in `tests/test_response_formatter.py`: `is_formattable(DATA_REPLY_PREFIX + "x")` is True.
4. Update `scripts/check_contracts.py` and CONTRACTS.md: the checks now verify consumers use the constants (e.g. the literal appears only in `reply_markers.py`, and each former site imports it).
5. Validation, commit `T-030: Centralize cross-file reply-marker strings`.

## Acceptance criteria
- `grep -rn "Here are the details on file" app/ | grep -v reply_markers` → only comment/alias hits, no second literal definition.
- All previously passing tests still pass; the byte-values of user-visible replies are unchanged (assert: no test snapshot/message-text changes needed).

## Required tests
- New: formatter-prefix test (step 3).
- Regression: full suite green.

## Validation (run exactly)
```bash
python3 scripts/check_contracts.py && echo CONTRACTS-OK
.venv/bin/ruff check .
.venv/bin/python -m mypy app/
RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false \
  .venv/bin/python -m pytest tests/ -q
```

## Documentation updates
CONTRACTS.md site lists.

## ADR impact
None (no boundary change; a leaf constants module).

## Definition of Done
Acceptance criteria met; validation passes; single commit; STATUS.md updated.

## Rollback plan
`git revert <commit>` — pure refactor, no data or schema changes.
