# T-014 — Create docs/WIRE_FORMATS.md (OpenAI-compat contract)

**Phase:** 1 · **Complexity:** M · **Estimated session:** ~700 lines input; one new ~100-line file
**Risks addressed:** R-15

## Goal
The exact response shapes Open WebUI depends on are documented, with the surprising implementation facts (fake streaming, error-as-content, persistence inside the stream generator).

## Why this task exists
Breaking any invisible detail of the `/v1` envelope silently breaks the UI (R-15). A model editing `openai_compat.py` without this document will "clean up" the `-1` usage sentinels, the `data: [DONE]` terminator, or move persistence out of the generator — all plausible-looking, all breaking.

## Context required
- `docs/roadmap/README.md` §1
- this file
- `app/api/openai_compat.py` — read only these regions: ~87–181 (error shaping + direct-reply formatting), ~200–330 (model resolution, streaming), ~340–510 (endpoints, envelope)

## Files allowed to change
- `docs/WIRE_FORMATS.md` (create)

## Files forbidden to change
Everything else — especially `app/api/openai_compat.py` itself.

## Dependencies
None.

## Preconditions
```bash
test ! -f docs/WIRE_FORMATS.md && echo OK
grep -n '\[DONE\]' app/api/openai_compat.py       # SSE terminator exists
grep -n '"usage"' app/api/openai_compat.py | head # usage block with sentinel counts (~490-507)
```

## Steps
Create `docs/WIRE_FORMATS.md` documenting, each with file:line and a "DO NOT change without testing Open WebUI end-to-end" marker:
1. **Non-streaming envelope:** required fields `id`, `object="chat.completion"`, `created`, `model`, `choices[0].message`, `finish_reason`, and the `usage` block with sentinel `-1` token counts (real counts unavailable).
2. **Streaming framing:** `data: {json}\n\n` frames, `object="chat.completion.chunk"`, final chunk with `finish_reason="stop"`, then literal `data: [DONE]\n\n`.
3. **Streaming is simulated:** the full reply is generated first (tool loop must finish), then sliced into 6-char chunks; message persistence and summary scheduling happen INSIDE the stream generator — client disconnect mid-stream can lose the assistant message.
4. **Errors are content:** LLM failures return HTTP 200 with a friendly string as message content, not an HTTP error (both paths); cloud-unavailable is the exception (503 OpenAI-style error envelope).
5. **Log-context rebinding across the stream boundary:** `rebind_message(...)` / `reset_message()` in `finally` must be preserved.
6. **user_id resolution order** for `/v1`: `request.user` → `X-User-Id` → `X-OpenWebUI-User-Id` → `"openwebui-user"`; note that `/api/chat` takes `user_id` from the body, so the same person can map to different sessions per entry point.
7. **Model resolution:** unknown model IDs silently fall back to local.

## Acceptance criteria
- All seven items documented with verified file:line citations.

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
This task IS documentation. Optionally add a one-line pointer from `docs/OPENWEBUI.md` to the new file (allowed: that single line).

## ADR impact
None.

## Definition of Done
Acceptance criteria met; validation passes; single commit `T-014: Create docs/WIRE_FORMATS.md`; STATUS.md updated.

## Rollback plan
`git revert <commit>` — new file (plus at most one pointer line).
