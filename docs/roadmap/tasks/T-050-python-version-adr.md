# T-050 — ADR-0013: align the Python version story

**Phase:** 4 · **Complexity:** M · **Estimated session:** ~400 lines input; ADR + small config diffs
**Risks addressed:** R-03 · **Touches unknowns:** none, but requires ONE maintainer decision (see below)

## Goal
One documented Python version policy, consistently applied across `.python-version`, CI, `requires-python`, ruff, and mypy — recorded in ADR-0013.

## Why this task exists
Five files disagree about the Python version (R-03): `.python-version`=3.12, CI=3.11, `requires-python>=3.11`, ruff target py311, mypy 3.12. A model can ship 3.12-only syntax that CI (3.11) rejects, or avoid features it could use. This is a decision task — the ONLY roadmap task requiring maintainer input if the default below is not acceptable.

## Decision (default, use unless maintainer overrides)
**Policy:** runtime floor stays 3.11 (`requires-python`, ruff target unchanged — code must run on 3.11); CI tests BOTH 3.11 and 3.12 via a matrix; `.python-version` stays 3.12 for local dev; mypy stays 3.12 (needed to parse numpy stubs, per `pyproject.toml:53-54`). Rationale: preserves the deployed floor while making the local/CI split visible and tested instead of accidental.

## Context required
- `docs/roadmap/README.md` §1
- this file
- `.github/workflows/tests.yml` (~46 lines)
- `pyproject.toml` lines 1–10 and 37–60
- `.python-version` (1 line)
- `docs/adr/README.md` + ADR-0012 (process)

## Files allowed to change
- `docs/adr/0013-python-version-policy.md` (create)
- `docs/adr/README.md` (index row)
- `.github/workflows/tests.yml` (add the 3.12 matrix entry)
- `CLAUDE.md`, `docs/DEVELOPMENT.md` (update the version-facts lines)

## Files forbidden to change
- `pyproject.toml`, `.python-version` (unchanged under the default policy)
- Everything else.

## Dependencies
T-015 (ADR process exists).

## Preconditions
```bash
cat .python-version                                    # 3.12
grep -n "python-version" .github/workflows/tests.yml   # 3.11 only
test -f docs/adr/0012-adr-process.md && echo OK
```

## Steps
1. Write ADR-0013 stating the policy above (Context: the five-way disagreement, cite each file; Decision; Consequences: what a contributor must target — write code that runs on 3.11).
2. Convert the CI job to a matrix `python-version: ["3.11", "3.12"]` (keep everything else identical; the coverage gate runs per matrix entry — acceptable).
3. Update the environment-facts lines in CLAUDE.md and docs/DEVELOPMENT.md.
4. Push to a branch / open PR to observe both matrix legs green (if the 3.12 leg fails, STOP: record the failure in STATUS.md, mark BLOCKED — the failure itself is the valuable finding).
5. Commit `T-050: ADR-0013 Python version policy + CI matrix`.

## Acceptance criteria
- ADR-0013 exists, indexed; CI matrix runs 3.11 and 3.12; both legs green; docs updated.

## Required tests
CI itself (both legs). Local: standard validation block.

## Validation (run exactly)
```bash
.venv/bin/ruff check .
.venv/bin/python -m mypy app/
RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false \
  .venv/bin/python -m pytest tests/ -q
```

## Documentation updates
CLAUDE.md + DEVELOPMENT.md version facts; ADR index.

## ADR impact
Creates ADR-0013.

## Definition of Done
Acceptance criteria met; both CI legs observed green; single commit; STATUS.md updated.

## Rollback plan
`git revert <commit>` — CI returns to single 3.11 leg; ADR marked Superseded rather than deleted if policy is reversed later.
