# Memory System

## What is implemented

- SQLite persistence for users, sessions, and messages (`app/memory/store.py`)
- Active-session lifecycle manager (`app/memory/session.py`)
- Lightweight summary generation for session rollover (`app/memory/summarizer.py`)
- User/session APIs (`app/api/users.py`)

## API

- `POST /api/users` — create/update user profile
- `GET /api/users/{user_id}` — fetch profile
- `GET /api/sessions/{user_id}` — list sessions
- `POST /api/sessions/{user_id}/new` — close current session + open new one

## Chat Integration

`POST /api/chat` now:
1. Loads or creates the active session for `user_id`
2. Persists user and assistant messages in SQLite
3. Injects user profile and last session summary into system prompt when available

## Database Tables

- `users(user_id, name, profile_json, created_at)`
- `sessions(session_id, user_id, started_at, ended_at, summary)`
- `messages(id, session_id, role, content, created_at)`
