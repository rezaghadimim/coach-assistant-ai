# Open WebUI Integration (Phase 4)

## Overview

Phase 4 adds an **OpenAI-compatible API layer** to the Life Coach AI backend.
This allows [Open WebUI](https://github.com/open-webui/open-webui) — or any
client that speaks the OpenAI Chat Completions protocol — to connect to the
backend while retaining all coaching features:

- RAG context injection (Phase 2)
- Per-user SQLite session memory and summaries (Phase 3)
- Streaming and non-streaming responses

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
# Life Coach API docs at http://localhost:8000/docs
```

Open WebUI will automatically list `life-coach-ai` as an available model.

## Manual / curl Test

```bash
# Non-streaming
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-User-Id: alice" \
  -d '{
    "model": "life-coach-ai",
    "messages": [{"role": "user", "content": "I want to improve my focus."}]
  }'

# Streaming
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-User-Id: alice" \
  -d '{
    "model": "life-coach-ai",
    "messages": [{"role": "user", "content": "Help me plan my week."}],
    "stream": true
  }'
```

## Architecture

```text
Browser → Open WebUI (port 3000)
              ↓  OpenAI API protocol
          Life Coach API (port 8000)
              ├─ /v1/chat/completions  ← new (Phase 4)
              ├─ RAG retrieval
              ├─ SQLite memory
              └─ Ollama LLM
```

## Testing

```bash
python3 -m unittest tests/test_phase4_openwebui.py
```
