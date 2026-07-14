# T-017 — Create docs/DEVELOPMENT.md (dev/test guide)

**Phase:** 1 · **Complexity:** M · **Estimated session:** ~500 lines input; one new ~100-line file + 1 README line
**Risks addressed:** R-17, R-18

## Goal
A contributor (human or model) can set up, run, lint, type-check, and test the project from one document, with the known traps called out.

## Why this task exists
No developer-onboarding doc exists (R-17); the CI-safe test invocation is buried in OPERATIONS.md and the `unittest discover` trap is documented in exactly one place (R-18). CLAUDE.md (T-010) is the terse contract; this is the explanatory version.

## Context required
- `docs/roadmap/README.md` §1
- this file
- `CLAUDE.md` (created by T-010 — reuse its command block verbatim)
- `tests/conftest.py` (~40 lines)
- `.github/workflows/tests.yml` (~46 lines)

## Files allowed to change
- `docs/DEVELOPMENT.md` (create)
- `README.md` (add ONE line linking to docs/DEVELOPMENT.md in a suitable section)

## Files forbidden to change
Everything else.

## Dependencies
T-010 (CLAUDE.md must exist).

## Preconditions
```bash
test -f CLAUDE.md && echo OK              # OK (T-010 done)
test ! -f docs/DEVELOPMENT.md && echo OK  # OK
```

## Steps
Create `docs/DEVELOPMENT.md` covering:
1. **Setup:** Python version story as it stands (local `.python-version` 3.12, CI 3.11 — link ADR-0013 once T-050 lands), venv creation, `pip install -r requirements-dev.txt` (state explicitly: CI installs requirements files, not pyproject groups).
2. **Running the app** locally (Ollama prerequisites, `python3 main.py`) — copy from README, link rather than duplicate detail.
3. **Testing:** the env-pinned pytest command and WHY each pin exists (token backends avoid Ollama network hangs; formatter off avoids model downloads); the `unittest discover` trap (conftest sets `DEBUG=true` + temp DB; skipping it ⇒ auth 401s and writes to the real DB); how integration tests gate on env flags.
4. **Lint & types:** `ruff check .` (E/F only, E501 off), `mypy app/` (non-strict; six modules `ignore_errors` — list them, link T-040).
5. **Working a roadmap task:** 5-line summary of `docs/roadmap/README.md` §1 + link.
6. **What lives where:** docs/ = documentation only; app data under data/; scratch outputs never committed.

## Acceptance criteria
- All six sections present; every command executed once during the session.
- README.md diff is exactly one added line.

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
Acceptance criteria met; validation passes; single commit `T-017: Create docs/DEVELOPMENT.md`; STATUS.md updated.

## Rollback plan
`git revert <commit>`.
