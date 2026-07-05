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
3. Open WebUI forwarded headers (`ENABLE_FORWARD_USER_INFO_HEADERS=true` in
   docker-compose): `X-OpenWebUI-User-Id` and `X-OpenWebUI-User-Name`
4. Falls back to `"openwebui-user"` (shared session)

With `ENABLE_FORWARD_USER_INFO_HEADERS` enabled (default in docker-compose),
each logged-in coach gets their own session keyed on their WebUI user ID, and
their full display name is stored for the assistant context. Coach accounts are
excluded from patient/client lists (`list_clients`).

For manual per-user isolation without Open WebUI headers, set the `X-User-Id`
header in Open WebUI's *Connection → Headers* settings, or pass
`"user": "<id>"` from a custom pipe.

## Running with Docker Compose

```bash
# 1. Make sure Ollama is running locally and has the model pulled
ollama pull llama3.1:8b

# 2. (Optional) initialize private knowledge submodule and ingest
./scripts/setup_knowledge_private_repo.sh
python3 scripts/ingest.py

# 3. Start the stack
docker compose up --build

# Open WebUI is now available at http://localhost:3000
# Coach Assistant API docs at http://localhost:8000/docs (DEBUG=true only; disabled in production)
```

`docs/knowledge/starter/` holds bundled bootstrap docs (committed in this repo).
Your real documents live in the **`coach-knowledge`** private repo, linked as a
git submodule at `docs/knowledge/private/`. See
[`docs/knowledge/SETUP_PRIVATE_REPO.md`](knowledge/SETUP_PRIVATE_REPO.md).

Open WebUI will automatically list `coach-assistant-ai` (local) as an available
model. If you have configured `OPENROUTER_API_KEY`, a second model
`coach-assistant-ai-cloud` will also appear in the picker. See
[OpenRouter Integration](./OPENROUTER.md) for setup details.

## Model Picker Behaviour

Open WebUI stores connection settings in its `webui.db` volume by default. If you
previously enabled Ollama in the Admin UI, you may see raw Ollama models
(`llama3.1:8b`, cloud models, etc.) instead of `coach-assistant-ai`. This
project sets `ENABLE_PERSISTENT_CONFIG=false` in `docker-compose.yml` so
connection settings always come from environment variables, not stale UI saves.

| Scenario | Models listed in Open WebUI |
|---|---|
| No `OPENROUTER_API_KEY` set | `coach-assistant-ai` (local only) |
| API key set, OpenRouter reachable | `coach-assistant-ai` plus each slug in `OPENROUTER_MODELS` |
| API key set, OpenRouter unreachable | `coach-assistant-ai` (local only) |

The default model is always the local one. Open WebUI remembers your last
selection per chat, but new chats start on `coach-assistant-ai`.

## Authentication

`/v1/*` routes require the API key like every other router (see
[OPERATIONS.md](OPERATIONS.md)): send `X-API-Key: <key>` or
`Authorization: Bearer <key>`. Open WebUI passes its configured
`OPENAI_API_KEY` value as a Bearer token, so it must match the backend's
`API_KEY`. With `API_KEY` unset the backend fails closed — set `DEBUG=true`
for a local, auth-free stack.

## Manual / curl Test

```bash
# Non-streaming
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -H "X-User-Id: alice" \
  -d '{
    "model": "coach-assistant-ai",
    "messages": [{"role": "user", "content": "I want to improve my focus."}]
  }'

# Streaming
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
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
- They run as a **single plain completion with no tools** (`_generate_with_tools`
  returns early for tasks). This is deliberate: given the client CRUD tool
  definitions, the local 8B model would "helpfully" call DB tools based on chat
  history — issuing spurious reads and even re-emitting a `create_client` preview
  for a client the coach just confirmed. Meta-tasks only need the transcript Open
  WebUI already embeds in the prompt, so tools are withheld.
- Their JSON reply (e.g. `{ "follow_ups": [...] }`) is returned unmodified so
  Open WebUI's parser can render the suggestions.
- Because the coaching system prompt and chat context are still injected, the
  generated follow-ups and starters stay coaching-focused.

### Background load with local Ollama (dev tip)

Open WebUI fires **three** meta-tasks per interaction (follow-up suggestions,
chat title, tags), each a separate `/v1/chat/completions` request. With local
Ollama on an 8B model these run 15–30 s apiece and can keep the machine busy
well after the coach's last message. Withholding tools (above) removes the
biggest cost, but for a snappier local dev loop consider disabling
**follow-up suggestions**, **title generation**, and **tag generation** in
Open WebUI's *Admin Settings → Interface*.

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
