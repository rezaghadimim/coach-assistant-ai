"""LLM tool definitions and executor for client management via chat."""

from typing import Any, Optional

from app.memory.store import MemoryStore

_PROFILE_FIELDS = ("email", "phone", "age", "occupation", "background")
_CONFIRM_CLIENT_HINT = (
    "Are you sure you want to save this client? Reply yes or confirm to save."
)
_CONFIRM_NOTE_HINT = (
    "Are you sure you want to save this note? Reply yes or confirm to save."
)
_CONFIRM_UPDATE_NOTE_HINT = (
    "Are you sure you want to update this note? Reply yes or confirm to save."
)
_CONFIRM_DELETE_NOTE_HINT = (
    "Are you sure you want to delete this note? Reply yes or confirm to delete."
)
_CONFIRM_DELETE_CLIENT_HINT = (
    "Are you sure you want to delete this client and all their notes? "
    "Reply yes or confirm to delete."
)
_VALID_NOTE_TYPES = frozenset({"general", "story", "decision", "goal", "progress"})
_WRITE_TOOLS = frozenset(
    {
        "create_client",
        "add_client_note",
        "update_client_note",
        "delete_client_note",
        "delete_client",
    }
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


def sanitize_write_confirmation(
    tool_name: str,
    arguments: dict[str, Any],
    last_user: str,
) -> dict[str, Any]:
    """Ignore premature confirmed=true unless the user explicitly approved."""
    if tool_name not in _WRITE_TOOLS or not _is_confirmed(arguments):
        return arguments
    from app.core.confirmations import is_user_confirmation

    if is_user_confirmation(last_user):
        return arguments
    return {**arguments, "confirmed": False}


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
        f"{_CONFIRM_CLIENT_HINT}"
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
    lines.append(_CONFIRM_NOTE_HINT)
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


def _normalize_note_type(note_type: str) -> str:
    normalized = note_type.strip().lower()
    return normalized if normalized in _VALID_NOTE_TYPES else "general"


def _format_update_note_preview(
    note_id: int,
    client_id: str,
    content: str,
    note_type: str,
    title: Optional[str],
) -> str:
    lines = [
        "⏳ Update note — pending confirmation (not saved yet).",
        f"Note ID: {note_id}",
        f"Client: {client_id}",
        f"Type: {note_type}",
    ]
    if title:
        lines.append(f"Title: {title}")
    lines.append(f"Content: {content}")
    lines.append("")
    lines.append(_CONFIRM_UPDATE_NOTE_HINT)
    return "\n".join(lines)


def _format_delete_note_preview(note_id: int, client_id: str, note: dict[str, Any]) -> str:
    header = f"[{note['note_type'].upper()}]"
    if note.get("title"):
        header += f" {note['title']}"
    return (
        "⏳ Delete note — pending confirmation (not deleted yet).\n\n"
        f"Note ID: {note_id}\n"
        f"Client: {client_id}\n"
        f"Type: {note['note_type']}\n"
        f"Content: {note['content']}\n\n"
        f"{_CONFIRM_DELETE_NOTE_HINT}"
    )


def _format_delete_client_preview(user: dict[str, Any], note_count: int) -> str:
    name = user.get("name") or user["user_id"]
    return (
        "⏳ Delete client — pending confirmation (not deleted yet).\n\n"
        f"Client ID: {user['user_id']}\n"
        f"Name: {name}\n"
        f"Notes on file: {note_count}\n\n"
        f"{_CONFIRM_DELETE_CLIENT_HINT}"
    )


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
                        "description": (
                            "Client identifier or display name (e.g. 'ali' or 'Ali'). "
                            "For new clients use a short lowercase id."
                        ),
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
                "Only when the coach explicitly asks to save or document information — "
                "not when they ask for coaching advice, techniques, or suggestions. "
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
                        "description": (
                            "Client identifier or display name (must already exist)"
                        ),
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
                        "description": (
                            "Client identifier or display name "
                            "(e.g. 'ali' or 'Ali')"
                        ),
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
    {
        "type": "function",
        "function": {
            "name": "update_client_note",
            "description": (
                "Update an existing client note by id. Always preview first, then "
                "call again with confirmed=true after the coach approves."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "confirmed": {"type": "boolean"},
                    "note_id": {"type": "integer", "description": "Note id to update"},
                    "content": {"type": "string", "description": "New note text"},
                    "note_type": {
                        "type": "string",
                        "enum": ["general", "story", "decision", "goal", "progress"],
                    },
                    "title": {"type": "string"},
                },
                "required": ["note_id", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_client_note",
            "description": (
                "Delete a client note by id. Always preview first, then call again "
                "with confirmed=true after the coach approves."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "confirmed": {"type": "boolean"},
                    "note_id": {"type": "integer", "description": "Note id to delete"},
                },
                "required": ["note_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_client",
            "description": (
                "Delete a client and all their notes. Always preview first, then "
                "call again with confirmed=true after the coach approves."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "confirmed": {"type": "boolean"},
                    "client_id": {
                        "type": "string",
                        "description": "Client identifier or display name to delete",
                    },
                },
                "required": ["client_id"],
            },
        },
    },
]


def execute_tool(name: str, arguments: dict[str, Any], store: MemoryStore) -> str:
    """Execute a tool call and return the result as a string."""
    try:
        if name == "create_client":
            client_ref = arguments["client_id"]
            resolved_id = _resolve_client_id(store, client_ref)
            client_id = resolved_id or client_ref.strip()
            existing = store.get_user(client_id)
            client_name = (
                arguments.get("name")
                or (existing or {}).get("name")
                or client_ref
            )
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
            note_type = _normalize_note_type(arguments.get("note_type", "general"))
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

        if name == "update_client_note":
            note_id = int(arguments["note_id"])
            note = store.get_client_note(note_id)
            if note is None:
                return f"❌ Note '{note_id}' not found."
            content = arguments["content"]
            note_type = _normalize_note_type(
                arguments.get("note_type") or note["note_type"]
            )
            title = arguments["title"] if "title" in arguments else note.get("title")
            if not _is_confirmed(arguments):
                return _format_update_note_preview(
                    note_id,
                    note["user_id"],
                    content,
                    note_type,
                    title,
                )
            ok = store.update_client_note(
                note_id,
                content,
                title=title,
                note_type=note_type,
            )
            if not ok:
                return f"❌ Note '{note_id}' not found."
            return f"✅ Note (ID: {note_id}) updated for client '{note['user_id']}'."

        if name == "delete_client_note":
            note_id = int(arguments["note_id"])
            note = store.get_client_note(note_id)
            if note is None:
                return f"❌ Note '{note_id}' not found."
            if not _is_confirmed(arguments):
                return _format_delete_note_preview(note_id, note["user_id"], note)
            if not store.delete_client_note(note_id):
                return f"❌ Note '{note_id}' not found."
            return f"✅ Note (ID: {note_id}) deleted for client '{note['user_id']}'."

        if name == "delete_client":
            client_ref = arguments["client_id"]
            resolved_id = _resolve_client_id(store, client_ref)
            if resolved_id is None:
                return f"❌ Client '{client_ref}' not found."
            user = store.get_user(resolved_id)
            assert user is not None
            note_count = len(store.get_client_notes(resolved_id))
            if not _is_confirmed(arguments):
                return _format_delete_client_preview(user, note_count)
            if not store.delete_user(resolved_id):
                return f"❌ Client '{client_ref}' not found."
            return (
                f"✅ Client '{user.get('name') or resolved_id}' "
                f"(ID: {resolved_id}) and {note_count} note(s) deleted."
            )

        return f"❌ Unknown tool: {name}"

    except Exception as exc:  # noqa: BLE001
        return f"❌ Tool '{name}' failed: {exc}"
