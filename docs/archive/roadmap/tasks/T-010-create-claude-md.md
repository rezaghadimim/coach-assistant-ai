# T-010 — Create root CLAUDE.md (AI contract)

**Phase:** 1 · **Complexity:** M · **Estimated session:** ~600 lines input; one new ~80-line file
**Risks addressed:** R-17, R-18

## Goal
A root `CLAUDE.md` exists: the single file an AI session loads automatically, containing the commands and hard rules that prevent the known failure modes.

## Why this task exists
There is no AI/contributor contract anywhere in the repo (R-17). The known traps — pytest hangs on Ollama without env pins, `unittest discover` skips conftest, CI is Python 3.11 while local is 3.12, requirements files (not pyproject groups) drive CI (R-18, R-03) — live scattered in OPERATIONS.md and tribal knowledge.

## Context required
- `docs/roadmap/README.md` §1 and §2
- this file (the Steps section contains the full required content outline)
- `docs/roadmap/REPO_AUDIT.md` §4 ("Facts small models get wrong")
- `.github/workflows/tests.yml` (~46 lines) — to copy the exact CI commands/env

## Files allowed to change
- `CLAUDE.md` (create)

## Files forbidden to change
Everything else. Do NOT modify README.md in this task.

## Dependencies
None.

## Preconditions (verify before editing)
```bash
test ! -f CLAUDE.md && echo OK          # OK (no file exists yet)
grep -n "RAG_BACKEND" .github/workflows/tests.yml    # env pins present
```

## Steps
Create `CLAUDE.md` with exactly these sections (keep it under ~100 lines; link out instead of duplicating):
1. **What this repo is** — 3 lines (FastAPI coaching assistant, local Llama 3.1 8B via Ollama, SQLite, Open WebUI frontend).
2. **Commands** — verbatim: run tests (`RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false .venv/bin/python -m pytest tests/ -q`), lint (`ruff check .`), types (`mypy app/`), run app (`python3 main.py`). State: *never* `unittest discover`; tests hang on Ollama without the env pins.
3. **Environment facts** — CI = Python 3.11 + `requirements-dev.txt`; local `.python-version` = 3.12; pyproject `[dependency-groups]` are NOT what CI installs; mypy silences six modules (list them, cite `pyproject.toml`).
4. **Hard rules** — docs/ is documentation only, app data lives under data/; one commit per task; never edit files outside a task's allowed list; magic strings and tool-name lists are registered in `docs/CONTRACTS.md` (forward-reference; created by T-012); module layering in `docs/MODULE_MAP.md` (T-013); wire formats in `docs/WIRE_FORMATS.md` (T-014). Mark forward references clearly: "(if this file does not exist yet, the corresponding roadmap task has not run)".
5. **Roadmap pointer** — structured work items live in `docs/roadmap/` (protocol in its README §1; ledger STATUS.md).

## Acceptance criteria
- `CLAUDE.md` exists at repo root with the 5 sections above, < ~100 lines.
- Every command in it has been executed once during this task and worked (or its failure is noted in STATUS.md — see U-05).

## Required tests
None (docs-only), but Steps require actually running each documented command once.

## Validation (run exactly)
```bash
.venv/bin/ruff check .
.venv/bin/python -m mypy app/
RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false \
  .venv/bin/python -m pytest tests/ -q
```
Record the pytest result in STATUS.md — this also resolves U-05.

## Documentation updates
This task IS documentation. Also: add one line to README.md? **No** — forbidden here; noted for T-017.

## ADR impact
None.

## Definition of Done
Acceptance criteria met; validation run and results recorded; single commit `T-010: Create root CLAUDE.md (AI contract)`; STATUS.md updated (including U-05 row).

## Rollback plan
`git revert <commit>` — new file only.
