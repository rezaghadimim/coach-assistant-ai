# OpenAI-compatible wire formats (`/v1`)

Contract for Open WebUI (and any OpenAI Chat Completions client).  
**DO NOT change any detail below without testing Open WebUI end-to-end.**

Source: `app/api/openai_compat.py` (verified 2026-07-10; non-streaming pipeline note 2026-07-13).

---

## 0. Pipeline ownership

| Path | Orchestration |
|------|---------------|
| Non-streaming (`"stream": false`) | `app/api/chat_pipeline.run_chat_turn` (shared with `/api/chat`) |
| Streaming (`"stream": true`) | Inline in `openai_compat.py` — persistence intentionally duplicates `chat_pipeline` for SSE interleaving (see §3) |

**DO NOT** merge streaming into `run_chat_turn` without an explicit durability design + Open WebUI test.

---

## 1. Non-streaming envelope

`POST /v1/chat/completions` with `"stream": false` returns HTTP 200 JSON (`openai_compat.py:490-507`):

| Field | Required value / notes |
|-------|------------------------|
| `id` | `chatcmpl-{uuid}` |
| `object` | `"chat.completion"` |
| `created` | unix timestamp |
| `model` | resolved `model_id` |
| `choices[0].index` | `0` |
| `choices[0].message` | `{"role": "assistant", "content": <reply>}` |
| `choices[0].finish_reason` | `"stop"` |
| `usage` | `prompt_tokens` / `completion_tokens` / `total_tokens` all **`-1`** (real counts unavailable) |

**DO NOT** drop the `usage` block or replace `-1` with `0`/omit without Open WebUI verification.

---

## 2. Streaming framing

SSE (`media_type="text/event-stream"`). Each frame from `_make_chunk` (`:226-247`):

```text
data: {json}\n\n
```

Chunk JSON: `object="chat.completion.chunk"`, `choices[0].delta` / `finish_reason`.

Sequence in `_stream_text_reply` (`:250-268`):

1. Content chunks (see §3)
2. Final chunk with `finish_reason="stop"` (content omitted)
3. Literal terminator: `data: [DONE]\n\n` (`:268`)

**DO NOT** remove `[DONE]` or change the `data: …\n\n` framing.

---

## 3. Streaming is simulated

Tool-calling / generation finishes **before** any SSE bytes for the LLM path (`_stream_and_persist` `:299-313`): full reply is computed, then `_stream_text_reply` slices it into **6-character** chunks (`:257-259`).

**Persistence is inside the stream generator** (`:262-265`): `store.add_message(session_id, "assistant", reply)` and `schedule_update_summary` run after content chunks, before the stop/`[DONE]` frames.

Implication: a client disconnect mid-stream can lose the assistant message (user message was already persisted earlier at `:397-398`).

**DO NOT** move persistence out of the generator without an explicit durability design + Open WebUI test.

---

## 4. Errors are content (mostly)

LLM failures in `_generate_reply_or_unavailable` (`:164-181`) catch exceptions and return a **friendly string** as the assistant message — still HTTP 200 with a normal completion envelope.

Exceptions that are real HTTP errors:

| Case | Status | Shape |
|------|--------|-------|
| Cloud model requested but OpenRouter unavailable | **503** | OpenAI-style `{"error": {...}}` (`:361-374`) |
| Non-streaming wall-clock timeout | **504** | OpenAI-style `{"error": {...}}` (`:470-478`) |

**DO NOT** “fix” LLM-down paths to HTTP 5xx without checking Open WebUI’s error UX.

---

## 5. Log-context rebinding across the stream boundary

The request handler returns `StreamingResponse` before generation finishes. `_stream_and_persist` (`:287-320`) calls `rebind_message(msg_id, user_id)` at start and **`reset_message()` in `finally`**.

**DO NOT** drop the `finally: reset_message()` — log correlation and context leaks depend on it.

---

## 6. `user_id` resolution (`/v1` vs `/api/chat`)

`_resolve_user_id` (`:218-223`), used at `:376`:

1. `request.user` (JSON body field)
2. `X-User-Id` header
3. `X-OpenWebUI-User-Id` header
4. fallback `"openwebui-user"`

`/api/chat` takes `user_id` from its own request body — the **same human can map to different session keys** across the two entry points.

---

## 7. Model resolution

`effective_model_id()` (`:202-210`): known local IDs and cloud IDs are kept; **any other model string silently falls back to the local model id**.

**DO NOT** turn unknown models into hard 404s without an Open WebUI compatibility check.
