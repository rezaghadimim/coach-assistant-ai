# T-031 — Derive tool-name lists from TOOL_DEFINITIONS

**Phase:** 3 · **Complexity:** M · **Estimated session:** ~800 lines input; ~30-line diff
**Risks addressed:** R-06

## Goal
`llm_router._KNOWN_TOOLS` and the `_ROUTER_SCHEMA` tool enum are computed from `tools.TOOL_DEFINITIONS` instead of hand-maintained; adding a tool becomes a one-list edit (plus data files).

## Why this task exists
The 9 tool names live in four hand-synchronized lists (R-06). A model adding or renaming a tool will miss at least one list; the LLM router then silently rejects or never emits the tool.

## Context required
- `docs/roadmap/README.md` §1
- this file
- `docs/CONTRACTS.md` — tool-name table
- `app/core/llm_router.py` (entire file, ~202 lines)
- `app/core/tools.py` — only `TOOL_DEFINITIONS` (~line 237 onward) and `_WRITE_TOOLS` (~line 53)

## Files allowed to change
- `app/core/llm_router.py`
- `tests/test_llm_router.py` (add one sync test)
- `scripts/check_contracts.py`, `docs/CONTRACTS.md` (reflect the new derivation)

## Files forbidden to change
Everything else — especially `app/core/tools.py` (`TOOL_DEFINITIONS` stays the single source; `_WRITE_TOOLS` stays a hand list because it encodes a *property* of tools, not the roster — leave it, T-020 already checks it is a subset).

## Dependencies
T-012, T-020.

## Preconditions
```bash
python3 scripts/check_contracts.py && echo OK
grep -n "_KNOWN_TOOLS" app/core/llm_router.py    # hand-maintained set exists (~line 35)
python3 -c "from app.core.llm_router import _KNOWN_TOOLS; from app.core.tools import TOOL_DEFINITIONS; assert _KNOWN_TOOLS == {d['function']['name'] if 'function' in d else d['name'] for d in TOOL_DEFINITIONS} or True"   # just confirms both import cleanly
```

## Steps
1. Determine the exact shape of `TOOL_DEFINITIONS` entries (read the first entry; the name key may be `d["name"]` or nested under `d["function"]["name"]` — verify, do not assume).
2. In `llm_router.py`, replace the `_KNOWN_TOOLS` literal with a derivation from `TOOL_DEFINITIONS`. Import placement: check whether `llm_router` already imports from `app.core.tools` at module level; if a cycle exists (tools importing llm_router — verify with grep), derive lazily inside a function with a module-level cache, matching the file's existing in-function-import style (see docs/MODULE_MAP.md).
3. Replace the hard-coded enum list in `_ROUTER_SCHEMA` (~line 106) with the same derived list (the schema dict may need to be built by a function instead of a literal).
4. Add `tests/test_llm_router.py::test_known_tools_match_definitions`: derived set equals `{name for TOOL_DEFINITIONS}` and is non-empty (≥ 9).
5. Update `scripts/check_contracts.py`: the tool-name check now asserts derivation still holds (keep the check — it guards against someone reverting to a literal).
6. Validation, commit `T-031: Derive tool-name lists from TOOL_DEFINITIONS`.

## Acceptance criteria
- No hard-coded list of all 9 tool names remains in `llm_router.py` (`grep -n "create_client" app/core/llm_router.py` → no enum-literal hits).
- Router behavior unchanged: full suite green, incl. `tests/test_llm_router.py` and `tests/test_eval_llm_router.py`.

## Required tests
Step-4 sync test; full regression suite.

## Validation (run exactly)
```bash
python3 scripts/check_contracts.py && echo CONTRACTS-OK
.venv/bin/ruff check .
.venv/bin/python -m mypy app/
RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false \
  .venv/bin/python -m pytest tests/ -q
```

## Documentation updates
CONTRACTS.md tool-name table (now: one code source + data files).

## ADR impact
None.

## Definition of Done
Acceptance criteria met; validation passes; single commit; STATUS.md updated.

## Rollback plan
`git revert <commit>` — behavior-preserving derivation.
