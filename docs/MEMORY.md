# Memory System

## What is implemented

- SQLite persistence for users, sessions, messages, and **client notes** (`app/memory/store.py`)
- Active-session lifecycle manager (`app/memory/session.py`)
- Structured coaching session summary generation (`app/memory/summarizer.py`)
- User/session/client-notes APIs (`app/api/users.py`)

## API

- `POST /api/users` — create/update user profile
- `GET /api/users/{user_id}` — fetch profile
- `GET /api/sessions/{user_id}` — list sessions
- `POST /api/sessions/{user_id}/new` — close current session + open new one
- `POST /api/clients/{user_id}/notes` — add a client note (story, decision, goal, progress)
- `GET /api/clients/{user_id}/notes` — list client notes (filterable by type)
- `PUT /api/clients/{user_id}/notes/{note_id}` — update a client note
- `DELETE /api/clients/{user_id}/notes/{note_id}` — delete a client note

## Chat Integration

`POST /api/chat` now:
1. Loads or creates the active session for `user_id`
2. Persists user and assistant messages in SQLite
3. Injects user profile, client notes/stories/decisions, and last session summary into system prompt
4. Exposes LLM tools so coaches can manage clients from natural-language chat

### Chat Tools (via LLM)

Coaches can say things like "Add Ali as a client" or "Save Sara's goal" in chat.
The model calls tools defined in `app/core/tools.py`.

Authoritative source: `TOOL_DEFINITIONS` in `app/core/tools.py` — update this table when that list changes.

| Tool | Purpose |
|------|---------|
| `create_client` | Create or update a client (patient/visitor) profile (preview then confirm) |
| `add_client_note` | Add a note, story, goal, decision, or progress update for a client |
| `get_client` | Retrieve a client's profile and contact information only (no notes) |
| `get_client_full` | Retrieve a client's complete record: profile, contact details, and all notes |
| `list_client_notes` | List all notes for a client, optionally filtered by type |
| `list_clients` | List all registered clients |
| `update_client_note` | Update an existing client note by id (preview then confirm) |
| `delete_client_note` | Delete a client note by id (preview then confirm) |
| `delete_client` | Delete a client and all their notes (preview then confirm) |

The REST API endpoints below remain available for direct CRUD from other clients.

## Client Notes

Each client has a documented file of notes that serve as ongoing documentation:
- **general** — general observations and context
- **story** — client background stories and personal history
- **decision** — decisions made during coaching (updated when revised)
- **goal** — goals set during sessions
- **progress** — progress updates on previous goals

These notes are automatically injected into the system prompt so the AI
coach references them naturally during conversations.

## Database Tables

- `users(user_id, name, profile_json, created_at)`
- `sessions(session_id, user_id, started_at, ended_at, summary)`
- `messages(id, session_id, role, content, created_at)`
- `client_notes(id, user_id, session_id, note_type, title, content, created_at, updated_at)`
