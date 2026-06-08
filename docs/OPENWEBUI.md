# Open WebUI Integration (Phase 4)

## Overview

Phase 4 adds an **OpenAI-compatible API layer** to the Coach Assistant AI backend.
This allows [Open WebUI](https://github.com/open-webui/open-webui) — or any
client that speaks the OpenAI Chat Completions protocol — to connect to the
backend while retaining all coaching features:

- RAG context injection (Phase 2)
- Per-user SQLite session memory, client notes, and summaries (Phase 3)
- Streaming and non-streaming responses
- Chat-based client management via LLM tool calling (same as `/api/chat`)

The UI is branded as **Coach Assistant AI** with `WEBUI_NAME` set in docker-compose.

## New Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/models` | List available coaching models |
| `POST` | `/v1/chat/completions` | OpenAI-compatible chat completion |

## User Identification

Open WebUI does not natively pass a coaching-session user ID.  The backend
resolves it with the following priority:

1. `"user"` field in the request JSON body
2. `X-User-Id` HTTP request header
3. Falls back to `"openwebui-user"` (shared session)

For per-user isolation, set the `X-User-Id` header in Open WebUI's
*Connection → Headers* settings, or pass `"user": "<id>"` from a custom pipe.

## Running with Docker Compose

```bash
# 1. Make sure Ollama is running locally and has the model pulled
ollama pull llama3.1:8b

# 2. (Optional) seed the knowledge base
python scripts/ingest.py --docs-dir ./docs/knowledge/

`docs/knowledge/` is intended for local-only source documents. Keep private knowledge
outside git and use the tracked sample file as a template.

# 3. Start the stack
docker compose up --build

# Open WebUI is now available at http://localhost:3000
# Coach Assistant API docs at http://localhost:8000/docs
```

Open WebUI will automatically list `coach-assistant-ai` as an available model.

## Manual / curl Test

```bash
# Non-streaming
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-User-Id: alice" \
  -d '{
    "model": "coach-assistant-ai",
    "messages": [{"role": "user", "content": "I want to improve my focus."}]
  }'

# Streaming
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-User-Id: alice" \
  -d '{
    "model": "coach-assistant-ai",
    "messages": [{"role": "user", "content": "Help me plan my week."}],
    "stream": true
  }'
```

## Streaming Behavior

When `"stream": true`, the backend first runs the full tool-calling loop
(non-streaming) so client-management actions complete before any text is sent.
The final coaching reply is then streamed to Open WebUI in small chunks.

This means there may be a pause before the first token when the model invokes
tools (e.g. saving a client note), but the streamed content is always the
complete, tool-resolved answer.

## Coaching-only Scope & Follow-up Suggestions

The backend stays focused on coaching. Clearly off-topic user requests (writing
code, math, weather, trivia, translation, recipes, current news, etc.) are
declined with a fixed coaching redirect — enforced both by the system prompt and
a deterministic guardrail (`app/core/scope.py`) that short-circuits before any
LLM call.

Open WebUI's hidden **task** requests (follow-up suggestions, chat title, and
tag generation) are detected and always allowed through:

- They bypass the scope guardrail and client-lookup shortcuts.
- Their JSON reply (e.g. `{ "follow_ups": [...] }`) is returned unmodified so
  Open WebUI's parser can render the suggestions.
- Because the coaching system prompt and chat context are still injected, the
  generated follow-ups and starters stay coaching-focused.

## Architecture

```text
Browser → Open WebUI "Coach Assistant AI" (port 3000)
              ↓  OpenAI API protocol
          Coach Assistant API (port 8000)
              ├─ /v1/chat/completions  ← OpenAI-compat
              ├─ RAG retrieval
              ├─ SQLite memory + client notes
              ├─ LLM tool calling (client CRUD)
              └─ Ollama LLM
```

## Testing

```bash
python3 -m unittest tests/test_phase4_openwebui.py
```
