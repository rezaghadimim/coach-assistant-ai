# T-040 — mypy: un-ignore app.core.model_registry (repeatable recipe)

**Phase:** 3 · **Complexity:** M · **Estimated session:** ~500 lines input; type-annotation diff in one file
**Risks addressed:** R-14

## Goal
`app.core.model_registry` is removed from the mypy `ignore_errors` override and passes `mypy app/` cleanly. This task doubles as the RECIPE for the remaining five overridden modules.

## Why this task exists
The six mypy-silenced modules are exactly the hottest edit targets (R-14); silencing hides AI-introduced type errors from CI. `model_registry` (215 lines) is the smallest — the safest first cut and the template for the rest.

## Context required
- `docs/roadmap/README.md` §1
- this file
- `pyproject.toml` lines 50–80 (the override block)
- `app/core/model_registry.py` (entire file, ~215 lines)
- mypy output gathered in Steps

## Files allowed to change
- `pyproject.toml` (remove ONE module from the override list)
- `app/core/model_registry.py` (type annotations, narrow casts, `# type: ignore[code]` with reason comments — NO behavior changes)

## Files forbidden to change
- Any other module in the override list (one per task).
- Any runtime logic: if fixing a type error requires changing behavior, STOP — that is a bug discovery; record it in STATUS.md Notes and mark BLOCKED.

## Dependencies
None.

## Preconditions
```bash
grep -n '"app.core.model_registry"' pyproject.toml    # in the override list
.venv/bin/python -m mypy app/ | tail -1                # Success (baseline green)
```

## Steps
1. Remove `"app.core.model_registry"` from the override list; run `mypy app/`; save the error list.
2. Fix each error with the LEAST invasive option, in order of preference: (a) add a missing annotation; (b) narrow with `isinstance`/`assert x is not None`; (c) `cast(...)`; (d) `# type: ignore[<specific-code>]  # <one-line reason>`. Never use bare `# type: ignore`.
3. Behavior guard: `git diff` must show only annotations/comments/typing imports — no changed expressions, no reordered logic. Re-read your diff line by line against this rule.
4. Validation, commit `T-040: mypy un-ignore app.core.model_registry`.

**Recipe note for follow-up tasks (author them via TASK_TEMPLATE.md when scheduled):** repeat per module in ascending size — `app.api.chat` (post T-032), `app.core.tools`, `app.core.tool_router`, `app.api.openai_compat` (post T-033), `app.rag.retriever` (post T-038/39). Each is its own task and commit.

## Acceptance criteria
- Override list no longer contains `model_registry`; `mypy app/` exits 0.
- Zero behavior change (step-3 diff audit; full suite green).

## Required tests
Full regression suite; `tests/test_openrouter.py` and `tests/test_provider_retry.py` in particular (they exercise the registry).

## Validation (run exactly)
```bash
.venv/bin/python -m mypy app/ && echo MYPY-OK
.venv/bin/ruff check .
RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false \
  .venv/bin/python -m pytest tests/ -q
```

## Documentation updates
docs/DEVELOPMENT.md (if it exists): update the list of still-silenced modules.

## ADR impact
None.

## Definition of Done
Acceptance criteria met; validation passes; single commit; STATUS.md updated.

## Rollback plan
`git revert <commit>` — annotations only.
