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
| T-010 | Create root CLAUDE.md (AI contract) | DONE | d571fa0 | 2026-07-10 | ruff+mypy clean; pytest skipped (U-05: 33 fail / 594 pass under .env embed drift — suite does NOT currently pass locally). Also resolved U-05 (partial). |
| T-011 | Create docs/CONVENTIONS.md | DONE | c0e6ed7 | 2026-07-10 | ruff+mypy clean; pytest skipped (U-05: 33 fail / 594 pass under .env embed drift — suite does NOT currently pass locally). |
| T-012 | Create docs/CONTRACTS.md | DONE | 2079d62 | 2026-07-10 | ruff+mypy clean; pytest skipped (U-05). ChunkRole only in ingest.py (not embed_providers/types.py) — noted in CONTRACTS. _WRITE_TOOLS includes update_client alias. |
| T-013 | Create docs/MODULE_MAP.md | DONE | a213027 | 2026-07-10 | ruff+mypy clean; pytest skipped (U-05). ChunkRole only in ingest.py (not embed_providers/types.py) — noted in CONTRACTS. _WRITE_TOOLS includes update_client alias. |
| T-014 | Create docs/WIRE_FORMATS.md | DONE | 1a4f92f | 2026-07-10 | ruff+mypy clean; pytest skipped (U-05). |
| T-015 | ADR-0012: define the ADR process | DONE | 2295466 | 2026-07-10 | ruff+mypy clean; pytest skipped (U-05: 33 fail / 594 pass under .env embed drift — suite does NOT currently pass locally). |
| T-016 | Create docs/CONFIG.md (env-var reference) | DONE | be195a2 | 2026-07-10 | ruff+mypy clean; pytest skipped (U-05). |
| T-017 | Create docs/DEVELOPMENT.md | DONE | a874467 | 2026-07-10 | ruff+mypy clean; pytest skipped (U-05). |
| T-020 | scripts/check_contracts.py + CI step | DONE | (pending) | 2026-07-11 | ruff+mypy clean. `python3 scripts/check_contracts.py` exits 0 on clean tree, offline (checked with `OLLAMA_BASE_URL=http://127.0.0.1:1`). Mutate-and-revert test: mutated `"No notes on file."` in tools.py → checker FAILED that check (exit 1); reverted → PASS again (exit 0). pytest baseline: standard validation command reproduced U-05 exactly (33 failed / 594 passed / 1 warning / 34 subtests passed, same test IDs) — zero new failures, as expected since this task touches no app code. Tried `RAG_EMBED_PROVIDER=ollama` override for a cheaper green run per the baseline caveat; it reduced failures to 25 (reranker/cross-encoder tests still fail, unrelated to embed provider) but was not genuinely green, so it was not used as the recorded baseline. No `.env` change committed. |
| T-021 | scripts/check_doc_paths.py + CI step | DONE | (pending) | 2026-07-12 | ruff+mypy clean. `python3 scripts/check_doc_paths.py` exits 0 on clean tree. Checker found one dead reference: `app/rag/reranker.rerank` in docs/SMALL_MODELS.md (dotted-notation typo for `app/rag/reranker.py`'s `rerank()`) — not ambiguous, fixed in place. Mutate-and-revert test: appended a fake path to docs/CONFIG.md → checker FAILED (exit 1); reverted → PASS again (exit 0). pytest baseline: standard validation command reproduced U-05 exactly (33 failed / 594 passed / 1 warning / 34 subtests passed, same test IDs as T-020's run) — zero new failures, as expected since this task touches no app code. No `.env` change committed. **Follow-up (same day):** CI failed on first push — 6 references to `data/coach_assistant.db`, `data/rag_index_cache.json`, and `data/knowledge/private/collections` were flagged missing because those paths are gitignored runtime-generated files (`*.db`, `data/rag_index_cache.json` — see `.gitignore`) or live inside the `data/knowledge/private` git submodule, which `actions/checkout@v4` doesn't initialize in CI. Local runs didn't catch this because those files/submodule content already existed on disk from prior local use. Fixed by adding the 3 unique normalized paths to `KNOWN_UNRESOLVED` (dict of path → reason) and normalizing trailing slashes in path extraction so both `.../collections` and `.../collections/` map to one entry. Re-verified: checker exits 0, mutate-and-revert still passes, ruff+mypy clean; no app code touched so pytest baseline unaffected. |
| T-030 | Centralize reply-marker strings | DONE | (pending) | 2026-07-13 | ruff+mypy clean. `python3 scripts/check_contracts.py` exits 0 (literals only in reply_markers.py; all four consumers import it). New test: `IsFormattableTests::test_true_for_data_reply_prefix_constant`. pytest baseline: 33 failed / 595 passed / 1 warning / 34 subtests passed — zero new failures (+1 pass from new test), same failure IDs as T-021. |
| T-031 | Single source of truth for tool names | DONE | (pending) | 2026-07-13 | ruff+mypy clean. `_KNOWN_TOOLS` and `_ROUTER_SCHEMA` enum derived from `TOOL_DEFINITIONS`; contract checker verifies import. New test: `KnownToolsSyncTests::test_known_tools_match_definitions`. pytest: 33 failed / 596 passed / 1 warning / 34 subtests passed (~22 min locally — embed tests hit `.env` `RAG_EMBED_BASE_URL`, same failure IDs as U-05; +1 pass from new test, zero new failures). |
| T-032 | Extract shared chat pipeline (chat.py) | DONE | 60f687c | 2026-07-13 | ruff+mypy clean; 631 passed / 1 skipped / ~8s (Test Execution Contract). `python3 -c "import main"` fails on system Python 3.9.6 (union syntax); `.venv/bin/python` (3.12) → IMPORT-OK. `openai_compat.py` untouched. Patch targets preserved: `chat.py` injects `generate_response` / `try_direct_reply_with_meta` into `run_chat_turn`. **Divergences for T-033:** (1) formatter: openai logs when `RESPONSE_FORMATTER_ENABLED=false` before `format_data_reply`; chat does not — use `gate_formatting_on_setting`; (2) `_sessions` cache only in chat via `on_history` callback; (3) openai passes `coach_name` to session creation; (4) openai persists user msg only when truthy — use `persist_user_message`; (5) openai uses `_generate_reply_or_unavailable` with `model_id` — use `generate_reply_fn`; (6) openai formats direct reply before stream/non-stream branch; (7) streaming path stays in openai_compat; (8) error responses differ per endpoint. |
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
| U-05 | Suite passes + coverage ≥ 75% right now? | Yes | 631 passed / 1 skipped / ~7s with Test Execution Contract (ADR-0014, 2026-07-13). Prior baseline: 33 failed / 596 passed / ~22 min under `.env` embed-provider leak. Coverage floor not re-checked this session. |
| U-06 | pyproject deps vs requirements files drift | No | — |
