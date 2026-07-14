# T-035 — Move `_layer_availability` out of main.py

**Phase:** 3 · **Complexity:** M · **Estimated session:** ~700 lines input; small 3-file diff
**Risks addressed:** R-10

## Goal
`app/api/metrics.py` no longer imports from `main`; the layer-availability helper lives in a core module both can import.

## Why this task exists
`metrics.py:124` imports `_layer_availability` from the app entrypoint while `main.py` imports the metrics router — a call-time circular dependency (R-10). Any reorganization of `main.py` silently breaks `/metrics`, and the pattern teaches models that importing from `main` is acceptable.

## Context required
- `docs/roadmap/README.md` §1
- this file
- `docs/MODULE_MAP.md` (layering rules)
- `main.py` (entire file, ~308 lines) — locate `_layer_availability` and everything it references (incl. `_embed_probe_cache` if coupled)
- `app/api/metrics.py` (entire file, ~128 lines)

## Files allowed to change
- `app/core/health.py` (create)
- `main.py`
- `app/api/metrics.py`
- `tests/test_metrics.py`, `tests/test_observability.py` (patch-target strings only, if needed)

## Files forbidden to change
Everything else.

## Dependencies
T-013.

## Preconditions
```bash
grep -n "from main import\|import main" app/api/metrics.py    # the reverse import (~line 124)
grep -n "_layer_availability" main.py app/api/metrics.py       # definition + use sites
RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false \
  .venv/bin/python -m pytest tests/test_metrics.py -q           # green baseline
```

## Steps
1. Identify the full closure of `_layer_availability` in `main.py` (helpers, caches like `_embed_probe_cache`, imports). If it depends on FastAPI app state, STOP and mark BLOCKED with what you found — the move needs redesign by a maintainer.
2. Create `app/core/health.py`; move `_layer_availability` and its private helpers there verbatim, renaming to `layer_availability` (public — it is cross-module API now). Keep a `_layer_availability = layer_availability` alias in `main.py` importing from the new module (health endpoint keeps working; alias marked deprecated in a comment).
3. Point `metrics.py` at `app.core.health`. Remove the `from main import` line.
4. Validation incl. import check; commit `T-035: Move layer availability into app/core/health.py`.

## Acceptance criteria
- `grep -rn "import main" app/` → no hits.
- `/health` and `/metrics` behavior unchanged: `tests/test_metrics.py`, `tests/test_observability.py` green without assertion edits.

## Required tests
Full regression suite; step-4 import check.

## Validation (run exactly)
```bash
.venv/bin/ruff check .
.venv/bin/python -m mypy app/
RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false \
  .venv/bin/python -m pytest tests/ -q
python3 -c "import main" && echo IMPORT-OK
python3 -c "import app.api.metrics" && echo METRICS-IMPORT-OK
```

## Documentation updates
docs/MODULE_MAP.md: remove the "known violation" note for metrics.py; add `health.py` to the ownership table.

## ADR impact
None.

## Definition of Done
Acceptance criteria met; validation passes; single commit; STATUS.md updated.

## Rollback plan
`git revert <commit>` — pure code move with alias kept.
