# Roadmap status ledger

Single source of truth for progress. Update the row for your task **in the same commit** as the task's changes. Statuses: `TODO` · `IN-PROGRESS` · `DONE` · `BLOCKED` (precondition failed — add a note; a maintainer must revise the task file).

Session rule (from README.md §1): pick the first `TODO` task whose dependencies are all `DONE`. A task `IN-PROGRESS` with no commit sha means a session died mid-task: run `git status`; if the tree is dirty, `git checkout -- .` and restart that task.

| ID | Title | Status | Commit | Date | Notes |
|----|-------|--------|--------|------|-------|
| T-001 | Remove tracked junk files | DONE | 20ea828 | 2026-07-10 | Committed despite pre-existing pytest failures (U-05 / `.env` embed-provider drift); ruff+mypy clean. |
| T-002 | Fix .gitmodules submodule name | DONE | c92b434 | 2026-07-10 | ruff+mypy clean; pytest skipped (same U-05 pre-existing failures). Submodule status unchanged at 34c7489. |
| T-003 | Fix stale doc pointer in pyproject.toml | DONE | 2c380f0 | 2026-07-10 | ruff+mypy clean; pytest skipped (U-05). |
| T-004 | Correct stale facts in ARCHITECTURE.md | DONE | 9565ce1 | 2026-07-10 | ruff+mypy clean; pytest skipped (U-05). |
| T-005 | Correct tool table in MEMORY.md | DONE | 89a259e | 2026-07-10 | ruff+mypy clean; pytest skipped (U-05). |
| T-006 | Correct IMPLEMENTATION.md, mark historical | DONE | 44a32b8 | 2026-07-10 | ruff+mypy clean; pytest skipped (U-05). |
| T-007 | Annotate backfilled ADR dates | DONE | 4592bb0 | 2026-07-10 | ruff+mypy clean; pytest skipped (U-05). |
| T-010 | Create root CLAUDE.md (AI contract) | DONE | (pending) | 2026-07-10 | ruff+mypy clean; pytest skipped (U-05: 33 fail / 594 pass under .env embed drift — suite does NOT currently pass locally). Also resolved U-05 (partial). |
| T-011 | Create docs/CONVENTIONS.md | TODO | — | — | |
| T-012 | Create docs/CONTRACTS.md | TODO | — | — | |
| T-013 | Create docs/MODULE_MAP.md | TODO | — | — | |
| T-014 | Create docs/WIRE_FORMATS.md | TODO | — | — | |
| T-015 | ADR-0012: define the ADR process | TODO | — | — | |
| T-016 | Create docs/CONFIG.md (env-var reference) | TODO | — | — | |
| T-017 | Create docs/DEVELOPMENT.md | TODO | — | — | |
| T-020 | scripts/check_contracts.py + CI step | TODO | — | — | |
| T-021 | scripts/check_doc_paths.py + CI step | TODO | — | — | |
| T-030 | Centralize reply-marker strings | TODO | — | — | |
| T-031 | Single source of truth for tool names | TODO | — | — | |
| T-032 | Extract shared chat pipeline (chat.py) | TODO | — | — | |
| T-033 | openai_compat uses shared pipeline | TODO | — | — | |
| T-034 | KnowledgeStore migrations + PRAGMA parity | TODO | — | — | |
| T-035 | Move _layer_availability out of main.py | TODO | — | — | |
| T-036 | Resolve dead embed cache / write-only chunks | TODO | — | — | |
| T-037 | Public tokenizer API, end _private imports | TODO | — | — | |
| T-038 | Extract embedding-cache I/O from retriever | TODO | — | — | |
| T-039 | Extract citation formatting from retriever | TODO | — | — | |
| T-040 | mypy: un-ignore model_registry | TODO | — | — | |
| T-050 | ADR-0013: align Python version story | TODO | — | — | |

## Open unknowns carried between sessions

| ID | Unknown | Resolved? | Answer |
|----|---------|-----------|--------|
| U-01 | Single-tenant deployment? | No | — |
| U-02 | Callers of `embed_collection_chunks`? | No | — |
| U-03 | Is `knowledge_chunks` table read back? | No | — |
| U-04 | Worker/thread model vs unlocked indices | No | — |
| U-05 | Suite passes + coverage ≥ 75% right now? | Yes (partial) | Locally: 33 failed / 594 passed with CI env pins (2026-07-10). Failures look like `.env` making embed provider openai instead of ollama defaults — not a clean green suite. Coverage floor not re-checked this session. |
| U-06 | pyproject deps vs requirements files drift | No | — |
