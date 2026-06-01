# Architecture

> This document describes the system architecture. It is written for humans, GitHub Copilot, and Cursor AI to understand how components connect.

## Overview

```
┌─────────────────────────────────────────────────────┐
│                   Coach's Machine                     │
│                                                       │
│  ┌──────────┐    ┌──────────┐    ┌───────────────┐  │
│  │  Web UI  │───▶│ FastAPI  │───▶│  Ollama       │  │
│  │ (browser)│◀───│ Backend  │◀───│  (Llama 3.1)  │  │
│  └──────────┘    └────┬─────┘    └───────────────┘  │
│                       │                               │
│              ┌────────┼────────┐                      │
│              ▼        ▼        ▼                      │
│       ┌──────────┐ ┌──────┐ ┌──────────┐            │
│       │ ChromaDB │ │SQLite│ │ Prompts  │            │
│       │ (vectors)│ │(memory)│ │ (config) │            │
│       └──────────┘ └──────┘ └──────────┘            │
└─────────────────────────────────────────────────────┘
```

## Components

### 1. Ollama + Llama 3.1 8B
- **Role:** Generate coaching responses
- **Why local:** Zero cost, full privacy, no internet needed
- **Config:** Quantized 4-bit (Q4_K_M) for speed on consumer GPUs

### 2. FastAPI Backend (`app/`)
- **Role:** Orchestrates RAG, memory, and LLM calls
- **Endpoints:**
  - `POST /chat` — Main conversation endpoint
  - `POST /ingest` — Upload new coaching documents
  - `GET /sessions/{user_id}` — Retrieve past sessions
  - `POST /users` — Create new client profile

### 3. RAG Pipeline (`app/rag/`)
- **Role:** Retrieve relevant coaching knowledge before generating response
- **Vector Store:** ChromaDB (local, file-based, no server needed)
- **Embedding Model:** `nomic-embed-text` via Ollama (local, free)
- **Chunk Strategy:** 512 tokens, 50 token overlap

### 4. Memory System (`app/memory/`)
- **Role:** Remember client history across sessions
- **Storage:** SQLite
- **Two layers:**
  - **Short-term:** Current session messages (in-memory list)
  - **Long-term:** Session summaries + client profile (DB)

### 5. Web UI
- **Option A:** [Open WebUI](https://github.com/open-webui/open-webui) (pre-built, full-featured)
- **Option B:** Custom minimal UI (Jinja2 templates or React)
- **Served by:** FastAPI static files or separate process

## Data Flow (Single Request)

```
1. Coach types message in Web UI
2. Frontend sends POST /chat {user_id, message}
3. Backend retrieves:
   a. Relevant docs from ChromaDB (RAG)
   b. Client profile + last session summary from SQLite
   c. Current session messages from memory
4. Backend builds prompt:
   [system_prompt] + [rag_context] + [client_profile] + [history] + [user_message]
5. Backend calls Ollama API (localhost:11434)
6. Ollama returns generated response
7. Backend saves message to session history
8. Backend returns response to frontend
9. If session > 20 messages: auto-summarize and store
```

## Tech Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Language | Python | Best ML/AI ecosystem |
| Framework | FastAPI | Async, fast, easy |
| LLM Runtime | Ollama | Simple, one command |
| Vector DB | ChromaDB | No server, pip install |
| Database | SQLite | Zero config, single user |
| Embeddings | nomic-embed-text | Local, free, good quality |

## File Map

```
app/
├── api/
│   ├── __init__.py
│   ├── chat.py          # POST /chat endpoint
│   ├── ingest.py        # POST /ingest endpoint
│   └── users.py         # User/session management
├── core/
│   ├── __init__.py
│   ├── config.py        # Settings (model name, chunk size, etc.)
│   ├── llm.py           # Ollama client wrapper
│   └── prompts.py       # System prompts for coaching
├── rag/
│   ├── __init__.py
│   ├── ingest.py        # Document chunking & embedding
│   └── retriever.py     # Query ChromaDB for relevant chunks
├── memory/
│   ├── __init__.py
│   ├── session.py       # Current session message buffer
│   ├── store.py         # SQLite operations
│   └── summarizer.py    # Auto-summarize long sessions
└── models/
    ├── __init__.py
    └── schemas.py       # Pydantic models (User, Message, Session)
```
