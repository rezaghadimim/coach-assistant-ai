# Architecture

## Overview

```text
Web/API Client -> FastAPI -> Ollama
                     | \
                     |  -> Local RAG Index (in-memory)
                     -> SQLite Memory Store
```

## Implemented Components

### 1) Chat API (`app/api/chat.py`)
- Main endpoint: `POST /api/chat`
- Loads active session history from SQLite
- Injects optional RAG context and client profile into system prompt
- Persists user/assistant messages

### 2) RAG Ingestion + Retrieval (`app/rag/`)
- `ingest.py`: document discovery + chunking (`.txt`, `.md`, `.pdf`)
- `retriever.py`: token-based similarity index/query
- `POST /api/ingest`: reindex local document directory

### 3) Memory System (`app/memory/`)
- `store.py`: SQLite schema + CRUD for users/sessions/messages
- `session.py`: active session lifecycle and rollover
- `summarizer.py`: deterministic session summary generation
- `app/api/users.py`: user/session endpoints

## Data Flow

1. Client sends `POST /api/chat {user_id, message}`
2. Backend gets/creates active session for `user_id`
3. Backend retrieves top matching chunks from local RAG index
4. Backend composes system prompt with:
   - base coaching prompt
   - RAG context (if available)
   - user profile
   - previous session summary
5. Backend calls Ollama and stores reply in SQLite

## Current File Map

```text
app/
├── api/
│   ├── chat.py
│   ├── ingest.py
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
