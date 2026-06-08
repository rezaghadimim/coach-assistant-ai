# Architecture

## Overview

```text
Open WebUI (browser) → FastAPI ─────────────────────────────────────┐
                           |                                         │
                           ├─ /v1/chat/completions (model=local)  → Ollama (local)
                           ├─ /v1/chat/completions (model=cloud)  → OpenRouter (optional)
                           |                                         │
                           ├─ Local RAG Index (in-memory)           │
                           └─ SQLite Memory Store                   │
                                 (users, sessions, messages,        │
                                  client notes)                     │
```

The cloud OpenRouter provider is optional and only activated when
`OPENROUTER_API_KEY` is set and the availability probe succeeds.
The local Ollama provider is always the default.

## Implemented Components

### 1) Chat API (`app/api/chat.py`)
- Main endpoint: `POST /api/chat`
- Loads active session history from SQLite
- Injects optional RAG context, client profile, client notes, and session summary into system prompt
- Persists user/assistant messages
- LLM tool calling for client management (create client, add notes, look up profiles)

### 2) RAG Ingestion + Retrieval (`app/rag/`)
- `ingest.py`: document discovery + chunking (`.txt`, `.md`, `.pdf`)
- `retriever.py`: token-based similarity index/query
- `POST /api/ingest`: reindex local document directory

### 3) Memory System (`app/memory/`)
- `store.py`: SQLite schema + CRUD for users/sessions/messages/client_notes
- `session.py`: active session lifecycle and rollover
- `summarizer.py`: structured coaching session summary generation
- `app/api/users.py`: user, session, and client notes endpoints

### 4) Client Notes System
- Per-client documentation: stories, decisions, goals, progress notes
- CRUD API: create, list (with type filter), update, delete
- Auto-injected into system prompt for conversation continuity
- Decisions can be updated when revised

### 5) LLM Tool Calling (`app/core/tools.py`, `app/core/llm.py`)
- Provider-agnostic agentic loop (up to 5 iterations)
- Tools: `create_client`, `add_client_note`, `get_client`, `get_client_full`, `list_client_notes`, `list_clients`, `update_client_note`, `delete_client_note`, `delete_client`
- Tool results formatted per provider (Ollama uses `tool_name`; OpenRouter uses `tool_call_id`)
- Profile updates merge with existing client data (partial updates do not wipe fields)

### 6) LLM Provider Abstraction (`app/core/llm_providers/`)
- `types.py`: `LLMProvider` protocol, `CompletionResult`, `ToolCall` dataclasses
- `ollama.py`: Ollama `/api/chat` client (always active)
- `openrouter.py`: OpenRouter `/chat/completions` client (optional, opt-in via `OPENROUTER_API_KEY`)
- `app/core/model_registry.py`: virtual model IDs, provider resolution, and cached availability probe

### 7) Open WebUI Integration (`app/api/openai_compat.py`)
- `GET /v1/models`: dynamic model list — local always, cloud when probe passes
- `POST /v1/chat/completions`: routes by `model` field to the appropriate provider
- Streaming resolves tool calls first, then streams the final reply in chunks
- Cloud model returns HTTP 503 when OpenRouter is unavailable
- User identification via `user` field or `X-User-Id` header
- `Dockerfile` + `docker-compose.yml` for full-stack deployment
- Coach-branded UI via WEBUI_NAME environment variable

## Data Flow

1. Client sends `POST /api/chat {user_id, message}`
2. Backend gets/creates active session for `user_id`
3. Backend retrieves top matching chunks from local RAG index
4. Backend composes system prompt with:
   - base coaching prompt
   - RAG context (if available)
   - user profile
   - client notes/stories/decisions
   - previous session summary
5. Backend resolves provider (Ollama or OpenRouter) from the virtual model ID
6. Provider executes the tool-calling loop and returns a final reply; result is stored in SQLite

## Current File Map

```text
app/
├── api/
│   ├── chat.py
│   ├── ingest.py
│   ├── openai_compat.py
│   └── users.py
├── core/
│   ├── config.py
│   ├── llm.py
│   ├── model_registry.py
│   ├── prompts.py
│   ├── scope.py
│   ├── tools.py
│   ├── client_intents.py
│   ├── confirmations.py
│   ├── intent_kb.py
│   └── llm_providers/
│       ├── types.py
│       ├── ollama.py
│       └── openrouter.py
├── rag/
│   ├── ingest.py
│   └── retriever.py
├── memory/
│   ├── session.py
│   ├── store.py
│   └── summarizer.py
└── models/
    └── schemas.py
```
