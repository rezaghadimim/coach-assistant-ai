"""Detect explicit user approval and replay pending write previews."""

from __future__ import annotations

import re
from typing import Any, Optional

_CONFIRM = re.compile(
    r"^(?:"
    r"yes(?:[,.!]?\s*(?:save|please|go\s+ahead|confirm(?:ed)?|do\s+it))?|"
    r"yeah|yep|"
    r"confirm(?:ed)?(?:\s+(?:and\s+)?save)?|"
    r"save(?:\s+it)?|"
    r"go\s+ahead|"
    r"ok(?:ay)?|"
    r"do\s+it|"
    r"please\s+save|"
    r"sounds\s+good|"
    r"(?:that(?:'s|'s| is)\s+)?(?:fine|correct|right)|"
    r"i(?:'m| am)\s+sure"
    r")\.?\s*$",
    re.IGNORECASE,
)
_CONFIRM_PREFIX = re.compile(r"^(?:yes|confirm|save|ok(?:ay)?)\b", re.IGNORECASE)
_PENDING_CLIENT_ID = re.compile(r"^Client ID:\s*(.+)$", re.MULTILINE)
_PENDING_CLIENT_NAME = re.compile(r"^Name:\s*(.+)$", re.MULTILINE)
_PENDING_PROFILE_FIELD = re.compile(
    r"^(Email|Phone|Age|Occupation|Background):\s*(.+)$",
    re.MULTILINE,
)
_PROFILE_FIELD_KEYS = {
    "email": "email",
    "phone": "phone",
    "age": "age",
    "occupation": "occupation",
    "background": "background",
}
_PENDING_NOTE_ID = re.compile(r"^Note ID:\s*(\d+)$", re.MULTILINE)
_PENDING_NOTE_CLIENT = re.compile(r"^Client:\s*(.+)$", re.MULTILINE)
_PENDING_NOTE_TYPE = re.compile(r"^Type:\s*(.+)$", re.MULTILINE)
_PENDING_NOTE_TITLE = re.compile(r"^Title:\s*(.+)$", re.MULTILINE)
_PENDING_NOTE_CONTENT = re.compile(r"^Content:\s*(.+)$", re.MULTILINE)


def is_user_confirmation(message: str) -> bool:
    text = message.strip()
    if not text:
        return False
    if _CONFIRM.match(text):
        return True
    return bool(_CONFIRM_PREFIX.search(text))


def parse_pending_write(messages: list[dict]) -> Optional[tuple[str, dict[str, Any]]]:
    """Read tool name and arguments from the most recent write preview."""
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        content = message.get("content", "")
        if not isinstance(content, str) or "pending confirmation" not in content:
            continue

        if "Delete client" in content:
            client_id_match = _PENDING_CLIENT_ID.search(content)
            if client_id_match:
                return (
                    "delete_client",
                    {"client_id": client_id_match.group(1).strip()},
                )
            continue

        if "Delete note" in content:
            note_id_match = _PENDING_NOTE_ID.search(content)
            if note_id_match:
                return ("delete_client_note", {"note_id": int(note_id_match.group(1))})
            continue

        if "Update note" in content:
            note_id_match = _PENDING_NOTE_ID.search(content)
            content_match = _PENDING_NOTE_CONTENT.search(content)
            if not note_id_match or not content_match:
                continue
            note_type_match = _PENDING_NOTE_TYPE.search(content)
            title_match = _PENDING_NOTE_TITLE.search(content)
            args: dict[str, Any] = {
                "note_id": int(note_id_match.group(1)),
                "content": content_match.group(1).strip(),
            }
            if note_type_match:
                args["note_type"] = note_type_match.group(1).strip()
            if title_match:
                args["title"] = title_match.group(1).strip()
            return ("update_client_note", args)

        if "Add note" in content:
            client_match = _PENDING_NOTE_CLIENT.search(content)
            content_match = _PENDING_NOTE_CONTENT.search(content)
            if not client_match or not content_match:
                continue
            note_type_match = _PENDING_NOTE_TYPE.search(content)
            title_match = _PENDING_NOTE_TITLE.search(content)
            note_args: dict[str, Any] = {
                "client_id": client_match.group(1).strip(),
                "content": content_match.group(1).strip(),
                "note_type": (
                    note_type_match.group(1).strip() if note_type_match else "general"
                ),
            }
            if title_match:
                note_args["title"] = title_match.group(1).strip()
            return ("add_client_note", note_args)

        if "Create client" in content or "Update client" in content:
            client_id_match = _PENDING_CLIENT_ID.search(content)
            name_match = _PENDING_CLIENT_NAME.search(content)
            if not client_id_match or not name_match:
                continue
            client_id = client_id_match.group(1).strip()
            name = name_match.group(1).strip()
            if name == "(not set)":
                name = client_id
            client_args: dict[str, Any] = {"client_id": client_id, "name": name}
            for field_match in _PENDING_PROFILE_FIELD.finditer(content):
                label = field_match.group(1).strip().lower()
                value = field_match.group(2).strip()
                if value == "(not set)":
                    continue
                key = _PROFILE_FIELD_KEYS.get(label)
                if key:
                    if key == "age":
                        try:
                            client_args[key] = int(value)
                        except ValueError:
                            client_args[key] = value
                    else:
                        client_args[key] = value
            return ("create_client", client_args)
    return None
