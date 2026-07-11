# T-011 — Create docs/CONVENTIONS.md

**Phase:** 1 · **Complexity:** M · **Estimated session:** ~800 lines input; one new ~120-line file
**Risks addressed:** R-17

## Goal
Undocumented code conventions are written down in one place, so a model matches the codebase style instead of guessing.

## Why this task exists
Real conventions exist only in code (R-17): the `_with_meta` twin-function pattern, emoji status markers, guardrail letters, in-function-import rule, settings access pattern, test style. A model that doesn't know a convention invents its own, producing style-inconsistent and sometimes broken code.

## Context required
- `docs/roadmap/README.md` §1
- this file (Steps list every convention to document, with its evidence location)
- Spot-verify each claim below at its cited location before writing it down.

## Files allowed to change
- `docs/CONVENTIONS.md` (create)

## Files forbidden to change
Everything else. This task documents conventions; it does not change or "improve" any of them.

## Dependencies
None.

## Preconditions (verify before editing)
```bash
test ! -f docs/CONVENTIONS.md && echo OK    # OK
```

## Steps
Create `docs/CONVENTIONS.md` documenting (verify each; drop any that no longer holds and note it in STATUS.md):
1. **Result-object twins:** `try_direct_*_with_meta` returns a dataclass; the bare-named twin returns `.reply` (legacy string). New code uses the `_with_meta` form (evidence: `app/core/llm.py:331`, `app/core/client_intents.py:638`).
2. **Tool outcome statuses + emoji markers:** `ToolOutcome.status` vocabulary and the ⏳/✅/❌ preview-prefix semantics (evidence: `app/core/tools.py:16-33`).
3. **Guardrail legend:** A/B/C/E, what each blocks, where each lives in `app/core/llm.py` (comments at `llm.py:116,149,178,508`; E = `_notes_grounded`, `llm.py:144`). There is no guardrail D.
4. **"Router" disambiguation:** `tool_router` (semantic embed/rerank), `llm_router` (LLM JSON classify), `_tool_router_action` (client_intents dispatch) are three different things.
5. **Settings access:** always `from app.core.config import settings` (module singleton, `config.py:379`); env var name = UPPER field name; never read `os.environ` directly in app code.
6. **In-function imports are deliberate** (circular-import breaks); do not lift them to module level (full rules land in MODULE_MAP.md / T-013 — link forward).
7. **Test conventions:** files `tests/test_<area>.py`; mostly `unittest.TestCase` (bare-pytest classes also accepted); no pytest marks — live tests gate on env flags (e.g. `RUN_RERANK_INTEGRATION=1`); run only via pytest; conftest sets `DEBUG=true` + temp DB.
8. **Migration rules:** `MIGRATIONS` in `app/memory/store.py:88-95` is append-only, never reorder.
9. **Naming debt (do not imitate):** cross-module imports of `_underscored` names exist but are deprecated (link T-037); singular/plural rerank filenames explained (engine `rerank.py`, transports `rerank_tei.py`/`rerank_openai_compat.py`, RAG facade `rag/reranker.py`).

## Acceptance criteria
- All nine items present with file:line evidence, each verified during the session.

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
Acceptance criteria met; validation passes; single commit `T-011: Create docs/CONVENTIONS.md`; STATUS.md updated.

## Rollback plan
`git revert <commit>` — new file only.
