"""LLM tool definitions and executor for client management via chat."""

import json
from typing import Any

from app.memory.store import MemoryStore

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "create_client",
            "description": (
                "Create or update a client (patient/visitor) profile. "
                "Use this when the coach wants to register a new client or update "
                "an existing client's contact information or background details."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "client_id": {
                        "type": "string",
                        "description": "Short unique identifier for the client (e.g. 'ali', 'sara-001'). Use lowercase, no spaces.",
                    },
                    "name": {"type": "string", "description": "Full name of the client"},
                    "phone": {"type": "string", "description": "Phone number"},
                    "email": {"type": "string", "description": "Email address"},
                    "age": {"type": "integer", "description": "Age of the client"},
                    "occupation": {"type": "string", "description": "Job or occupation"},
                    "background": {
                        "type": "string",
                        "description": "Any background information about the client",
                    },
                },
                "required": ["client_id", "name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_client_note",
            "description": (
                "Add a note, story, goal, decision, or progress update for a client. "
                "Use this to document important information about a client that should "
                "be remembered across sessions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "client_id": {
                        "type": "string",
                        "description": "Client identifier (must already exist)",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full text of the note",
                    },
                    "note_type": {
                        "type": "string",
                        "enum": ["general", "story", "decision", "goal", "progress"],
                        "description": (
                            "Type of note: 'general' for misc info, 'story' for background, "
                            "'decision' for committed decisions, 'goal' for coaching goals, "
                            "'progress' for updates on previous goals."
                        ),
                    },
                    "title": {
                        "type": "string",
                        "description": "Short title for the note (optional)",
                    },
                },
                "required": ["client_id", "content", "note_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_client",
            "description": "Retrieve a client's profile and contact information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "client_id": {
                        "type": "string",
                        "description": "Client identifier",
                    }
                },
                "required": ["client_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_client_notes",
            "description": "List all notes for a client, optionally filtered by type.",
            "parameters": {
                "type": "object",
                "properties": {
                    "client_id": {
                        "type": "string",
                        "description": "Client identifier",
                    },
                    "note_type": {
                        "type": "string",
                        "enum": ["general", "story", "decision", "goal", "progress"],
                        "description": "Filter notes by type (optional)",
                    },
                },
                "required": ["client_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_clients",
            "description": "List all registered clients. Use this when the coach asks who their clients are.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def execute_tool(name: str, arguments: dict[str, Any], store: MemoryStore) -> str:
    """Execute a tool call and return the result as a string."""
    try:
        if name == "create_client":
            client_id = arguments["client_id"]
            client_name = arguments["name"]
            existing = store.get_user(client_id)
            existing_profile = (existing or {}).get("profile") or {}
            updates = {
                k: v
                for k, v in arguments.items()
                if k not in ("client_id", "name") and v is not None
            }
            profile = {**existing_profile, **updates}
            store.upsert_user(client_id, name=client_name, profile=profile)
            return f"✅ Client '{client_name}' (ID: {client_id}) saved successfully."

        if name == "add_client_note":
            client_id = arguments["client_id"]
            if store.get_user(client_id) is None:
                return (
                    f"❌ Client '{client_id}' not found. "
                    "Please create the client first using create_client."
                )
            note_id = store.add_client_note(
                client_id,
                arguments["content"],
                note_type=arguments.get("note_type", "general"),
                title=arguments.get("title"),
            )
            return f"✅ Note (ID: {note_id}) added for client '{client_id}'."

        if name == "get_client":
            client_id = arguments["client_id"]
            user = store.get_user(client_id)
            if user is None:
                return f"❌ Client '{client_id}' not found."
            return json.dumps(user, ensure_ascii=False, indent=2)

        if name == "list_client_notes":
            client_id = arguments["client_id"]
            note_type = arguments.get("note_type")
            notes = store.get_client_notes(client_id, note_type=note_type)
            if not notes:
                label = f"of type '{note_type}'" if note_type else ""
                return f"No notes {label} found for client '{client_id}'."
            return json.dumps(notes, ensure_ascii=False, indent=2)

        if name == "list_clients":
            users = store.list_users()
            if not users:
                return "No clients registered yet."
            lines = [
                f"- {u['name'] or u['user_id']} (ID: {u['user_id']})" for u in users
            ]
            return "Registered clients:\n" + "\n".join(lines)

        return f"❌ Unknown tool: {name}"

    except Exception as exc:  # noqa: BLE001
        return f"❌ Tool '{name}' failed: {exc}"
