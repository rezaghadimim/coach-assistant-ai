# T-033 — Migrate openai_compat non-streaming path to shared pipeline

**Phase:** 3 · **Complexity:** L · **Estimated session:** ~1,200 lines input; openai_compat diff only
**Risks addressed:** R-04

## Goal
The non-streaming `/v1/chat/completions` path calls `chat_pipeline.run_chat_turn` instead of its own copy of the pipeline. Streaming keeps its current structure (it interleaves persistence with SSE — merging it is riskier and deliberately out of scope).

## Why this task exists
Completes R-04 for the non-streaming path: after this, a pipeline edit lands in one file. The streaming path still duplicates persistence logic; that residual is documented, not silently left.

## Context required
- `docs/roadmap/README.md` §1
- this file
- `docs/WIRE_FORMATS.md` (the envelope you must not break)
- `app/api/chat_pipeline.py` (from T-032)
- `app/api/openai_compat.py` (entire file, ~507 lines) — the largest read in this roadmap; budget accordingly
- STATUS.md notes from T-032 (the recorded divergence list)

## Files allowed to change
- `app/api/openai_compat.py`
- `app/api/chat_pipeline.py` (signature extensions only — no behavior change for chat.py)
- `tests/test_phase4_openwebui.py` (patch-target strings only, if needed)

## Files forbidden to change
- `app/api/chat.py`
- `app/core/**`
- Everything else.

## Dependencies
T-032.

## Preconditions
```bash
test -f app/api/chat_pipeline.py && echo OK
RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false \
  .venv/bin/python -m pytest tests/test_phase4_openwebui.py -q    # green baseline
```

## Steps
1. Map openai_compat's non-streaming flow (~394–483 pre-T-032 numbering) onto `run_chat_turn` parameters. Preserve openai_compat's OWN current behaviors exactly: formatter gating on `response_formatter_enabled`, its user-id resolution, its error-as-content shaping, and the exact response envelope (see WIRE_FORMATS.md).
2. Extend `run_chat_turn` only where a needed hook is missing; every extension defaults to chat.py's current behavior (chat.py must produce a byte-identical flow without edits).
3. Replace the non-streaming duplicate with the call. Do NOT touch `_stream_and_persist` / `_stream_text_reply` beyond what compiles; add a comment on the streaming path: `Persistence here intentionally duplicates chat_pipeline for SSE interleaving — see docs/WIRE_FORMATS.md.`
4. Validation; commit `T-033: openai_compat non-streaming uses shared pipeline`.

## Acceptance criteria
- Non-streaming `/v1/chat/completions` flows through `run_chat_turn`; the duplicated sequence is gone from that path.
- Envelope unchanged: `tests/test_phase4_openwebui.py` green without assertion edits.
- `app/api/chat.py` diff empty.

## Required tests
Regression: full suite; specifically `tests/test_phase4_openwebui.py`, `tests/test_summarizer.py`, `tests/test_metrics.py`.

## Validation (run exactly)
```bash
.venv/bin/ruff check .
.venv/bin/python -m mypy app/
RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false \
  .venv/bin/python -m pytest tests/ -q
python3 -c "import main" && echo IMPORT-OK
```

## Documentation updates
Note in docs/WIRE_FORMATS.md that non-streaming now shares the pipeline; streaming remains separate by design.

## ADR impact
None.

## Definition of Done
Acceptance criteria met; validation passes; single commit; STATUS.md updated.

## Rollback plan
`git revert <commit>` — restores the duplicate; chat.py unaffected.
