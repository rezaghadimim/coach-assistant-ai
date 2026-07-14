# T-032 — Extract shared chat pipeline (used by chat.py)

**Phase:** 3 · **Complexity:** L · **Estimated session:** ~1,200 lines input; new ~120-line module + chat.py slimming
**Risks addressed:** R-04

## Goal
The persist→history→direct-reply→prompt→generate→append-ideas→persist→schedule-summary sequence lives once, in `app/api/chat_pipeline.py`, and `app/api/chat.py` calls it. (`openai_compat.py` migrates separately in T-033.)

## Why this task exists
The pipeline is duplicated between `chat.py:160-206` and `openai_compat.py:394-483` and has already diverged (R-04). Every pipeline edit currently requires a mirrored edit a model won't know about.

## Context required
- `docs/roadmap/README.md` §1
- this file
- `docs/MODULE_MAP.md` (layering rules)
- `app/api/chat.py` (entire file, ~251 lines)
- `app/api/openai_compat.py` lines ~394–483 ONLY (to design a signature T-033 can use — do not modify)

## Files allowed to change
- `app/api/chat_pipeline.py` (create)
- `app/api/chat.py`
- `tests/test_phase1_core_chat.py` (only if patch targets must move — see Steps 5)

## Files forbidden to change
- `app/api/openai_compat.py` (T-033)
- `app/core/**` (the pipeline orchestrates; it must not change core behavior)
- Everything else.

## Dependencies
T-013.

## Preconditions
```bash
test ! -f app/api/chat_pipeline.py && echo OK
RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false \
  .venv/bin/python -m pytest tests/test_phase1_core_chat.py -q     # green baseline
```

## Steps
1. Read `chat.py`'s pipeline (~160–206) and the openai_compat variant side by side. List the divergences (known from the audit: formatter-flag gating differs at `openai_compat.py:152`; chat.py maintains legacy `_sessions`).
2. Design `run_chat_turn(...)` in `app/api/chat_pipeline.py`: parameters covering both callers' needs — at minimum `user_id`, `message`, `store`, `session_manager`, plus explicit flags/hooks for the divergences (e.g. `gate_formatting_on_setting: bool`). Return a result object carrying the reply text, session id, message ids, and the meta both callers need. The function must NOT read FastAPI request objects — plain data in, plain data out.
3. **Behavior parity is the acceptance bar for chat.py only:** preserve chat.py's current behavior exactly, including its formatter behavior (it does NOT gate on `response_formatter_enabled` today — keep that, pass the flag accordingly; unifying the gate is a maintainer decision recorded in STATUS.md, not made here).
4. Rewire `chat.py` to call `run_chat_turn`, keeping the legacy `_sessions` update in `chat.py` itself (endpoint-specific, stays out of the shared function).
5. If tests patch symbols on `app.api.chat` (e.g. `generate_response`) verify whether the pipeline module breaks the patch path; prefer importing those functions inside `chat_pipeline` the same way `chat.py` does today so existing patch targets keep working; only touch the test file if unavoidable, and only patch-target strings.
6. Validation, commit `T-032: Extract shared chat pipeline`.

## Acceptance criteria
- `chat.py` no longer contains the inline pipeline sequence; it delegates to `chat_pipeline.run_chat_turn`.
- Full suite green with NO assertion changes (patch-target string updates in step 5 are the only permitted test edits).
- `openai_compat.py` untouched (`git diff --stat` shows no changes there).

## Required tests
Regression: full suite, with special attention to `tests/test_phase1_core_chat.py`, `tests/test_client_notes.py`, `tests/test_summarizer.py`.

## Validation (run exactly)
```bash
.venv/bin/ruff check .
.venv/bin/python -m mypy app/
RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false \
  .venv/bin/python -m pytest tests/ -q
python3 -c "import main" && echo IMPORT-OK
```

## Documentation updates
Add `chat_pipeline.py` row to docs/MODULE_MAP.md ownership table.

## ADR impact
None (internal factoring within the api layer). If you find yourself changing a module boundary, STOP — that needs an ADR per docs/adr/0012.

## Definition of Done
Acceptance criteria met; validation passes; single commit; STATUS.md updated (record the divergence list from step 1 in Notes — T-033 needs it).

## Rollback plan
`git revert <commit>` — chat.py returns to the inline pipeline; no schema/data impact.
