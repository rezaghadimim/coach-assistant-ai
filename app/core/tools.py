"""LLM tool definitions and executor for client management via chat."""

from typing import Any, Optional

from app.memory.store import MemoryStore

_PROFILE_FIELDS = ("email", "phone", "age", "occupation", "background")
_CONFIRM_HINT = (
    "Ask the coach to confirm, then call the same tool again with confirmed=true."
)


def _resolve_client_id(store: MemoryStore, client_id_or_name: str) -> Optional[str]:
    """Match a client by exact id, case-insensitive id, or display name."""
    if store.get_user(client_id_or_name):
        return client_id_or_name

    needle = client_id_or_name.strip().lower()
    for user in store.list_users():
        if user["user_id"].lower() == needle:
            return user["user_id"]
        name = (user.get("name") or "").strip().lower()
        if name and name == needle:
            return user["user_id"]
    return None


def _format_client_profile(user: dict[str, Any]) -> str:
    profile = user.get("profile") or {}
    lines = [
        f"Client ID: {user['user_id']}",
        f"Name: {user.get('name') or '(not set)'}",
    ]
    for field in _PROFILE_FIELDS:
        value = profile.get(field)
        label = field.capitalize()
        lines.append(
            f"{label}: {value}" if value not in (None, "") else f"{label}: (not set)"
        )
    return "\n".join(lines)


def _is_confirmed(arguments: dict[str, Any]) -> bool:
    value = arguments.get("confirmed")
    if value is True:
        return True
    if isinstance(value, str) and value.strip().lower() in {"true", "yes", "1"}:
        return True
    return False


def _format_create_client_preview(
    client_id: str,
    client_name: str,
    profile: dict[str, Any],
    *,
    is_update: bool,
) -> str:
    action = "Update client" if is_update else "Create client"
    preview_user = {"user_id": client_id, "name": client_name, "profile": profile}
    return (
        f"⏳ {action} — pending confirmation (not saved yet).\n\n"
        f"{_format_client_profile(preview_user)}\n\n"
        f"{_CONFIRM_HINT}"
    )


def _format_add_note_preview(
    client_id: str,
    content: str,
    note_type: str,
    title: Optional[str],
) -> str:
    lines = [
        "⏳ Add note — pending confirmation (not saved yet).",
        f"Client: {client_id}",
        f"Type: {note_type}",
    ]
    if title:
        lines.append(f"Title: {title}")
    lines.append(f"Content: {content}")
    lines.append("")
    lines.append(_CONFIRM_HINT)
    return "\n".join(lines)


def _format_client_notes(notes: list[dict[str, Any]]) -> str:
    if not notes:
        return "No notes on file."
    lines: list[str] = []
    for note in notes:
        header = f"[{note['note_type'].upper()}]"
        if note.get("title"):
            header += f" {note['title']}"
        lines.append(f"- {header} ({note['updated_at']})")
        lines.append(f"  {note['content']}")
    return "\n".join(lines)

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "create_client",
            "description": (
                "Create or update a client (patient/visitor) profile. "
                "Always call first without confirmed to preview, then again with "
                "confirmed=true only after the coach explicitly approves."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "confirmed": {
                        "type": "boolean",
                        "description": (
                            "Set to true only after the coach explicitly confirms "
                            "the preview. Omit or false on the first call."
                        ),
                    },
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
                "Always call first without confirmed to preview, then again with "
                "confirmed=true only after the coach explicitly approves."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "confirmed": {
                        "type": "boolean",
                        "description": (
                            "Set to true only after the coach explicitly confirms "
                            "the preview. Omit or false on the first call."
                        ),
                    },
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
            "description": (
                "Retrieve a client's profile and contact information only "
                "(no notes). Use get_client_full when the coach wants everything."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "client_id": {
                        "type": "string",
                        "description": (
                            "Client identifier or display name "
                            "(e.g. 'ali' or 'Ali')"
                        ),
                    }
                },
                "required": ["client_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_client_full",
            "description": (
                "Retrieve a client's complete record: profile, contact details, "
                "and all saved notes/messages. Use when the coach asks for all "
                "data, full details, or everything about a client/patient."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "client_id": {
                        "type": "string",
                        "description": (
                            "Client identifier or display name "
                            "(e.g. 'ali' or 'Ali')"
                        ),
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
                if k not in ("client_id", "name", "confirmed") and v is not None
            }
            profile = {**existing_profile, **updates}
            if not _is_confirmed(arguments):
                return _format_create_client_preview(
                    client_id,
                    client_name,
                    profile,
                    is_update=existing is not None,
                )
            store.upsert_user(client_id, name=client_name, profile=profile)
            return f"✅ Client '{client_name}' (ID: {client_id}) saved successfully."

        if name == "add_client_note":
            client_ref = arguments["client_id"]
            resolved_id = _resolve_client_id(store, client_ref)
            if resolved_id is None:
                return (
                    f"❌ Client '{client_ref}' not found. "
                    "Please create the client first using create_client."
                )
            note_type = arguments.get("note_type", "general")
            title = arguments.get("title")
            content = arguments["content"]
            if not _is_confirmed(arguments):
                return _format_add_note_preview(resolved_id, content, note_type, title)
            note_id = store.add_client_note(
                resolved_id,
                content,
                note_type=note_type,
                title=title,
            )
            return f"✅ Note (ID: {note_id}) added for client '{resolved_id}'."

        if name in ("get_client", "get_client_full"):
            client_ref = arguments["client_id"]
            resolved_id = _resolve_client_id(store, client_ref)
            if resolved_id is None:
                return f"❌ Client '{client_ref}' not found."
            user = store.get_user(resolved_id)
            assert user is not None
            sections = ["## Profile\n" + _format_client_profile(user)]
            if name == "get_client_full":
                notes = store.get_client_notes(resolved_id)
                sections.append("## Notes\n" + _format_client_notes(notes))
            return "\n\n".join(sections)

        if name == "list_client_notes":
            client_ref = arguments["client_id"]
            resolved_id = _resolve_client_id(store, client_ref)
            if resolved_id is None:
                return f"❌ Client '{client_ref}' not found."
            note_type = arguments.get("note_type")
            notes = store.get_client_notes(resolved_id, note_type=note_type)
            if not notes:
                label = f"of type '{note_type}' " if note_type else ""
                return f"No notes {label}found for client '{resolved_id}'."
            return _format_client_notes(notes)

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
