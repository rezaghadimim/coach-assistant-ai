# Architecture

## Overview

```text
Open WebUI (browser) → FastAPI → Ollama
                           | \
                           |  → Local RAG Index (in-memory)
                           → SQLite Memory Store (users, sessions, messages, client notes)
```

## Implemented Components

### 1) Chat API (`app/api/chat.py`)
- Main endpoint: `POST /api/chat`
- Loads active session history from SQLite
- Injects optional RAG context, client profile, client notes, and session summary into system prompt
- Persists user/assistant messages

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

### 5) Open WebUI Integration (`app/api/openai_compat.py`)
- `GET /v1/models`: list available coaching models (coach-assistant-ai)
- `POST /v1/chat/completions`: OpenAI-compatible chat completion with streaming
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
5. Backend calls Ollama and stores reply in SQLite

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
│   └── prompts.py
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
