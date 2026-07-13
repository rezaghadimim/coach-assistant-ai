"""Detect explicit user approval and replay pending write previews."""

from __future__ import annotations

import re
from collections import OrderedDict
from typing import Any, Optional

from app.core.reply_markers import PENDING_CONFIRMATION_MARKER

# Structured pending-write state (AI-01): when a write preview is produced,
# its exact rendered text is mapped to the (tool_name, arguments) to replay on
# confirmation. Confirm-to-save therefore does not depend on re-parsing the
# preview wording; the legacy regex parse below remains only as a fallback for
# previews rendered before a restart.
_MAX_PENDING_WRITES = 32
_pending_writes: "OrderedDict[str, tuple[str, dict[str, Any]]]" = OrderedDict()


def register_pending_write(
    preview_text: str, tool_name: str, arguments: dict[str, Any]
) -> None:
    """Record the structured write behind a rendered preview."""
    if not preview_text:
        return
    args = {k: v for k, v in arguments.items() if k != "confirmed"}
    _pending_writes[preview_text] = (tool_name, args)
    _pending_writes.move_to_end(preview_text)
    while len(_pending_writes) > _MAX_PENDING_WRITES:
        _pending_writes.popitem(last=False)


def clear_pending_writes() -> None:
    """Drop all registered pending writes (tests / runtime reset)."""
    _pending_writes.clear()


def _lookup_pending_write(content: str) -> Optional[tuple[str, dict[str, Any]]]:
    """Match an assistant message against registered previews.

    Containment (not equality) because endpoints may append sections (e.g.
    expert ideas) to the assistant reply after the preview text.
    """
    for preview_text in reversed(_pending_writes):
        if preview_text in content:
            return _pending_writes[preview_text]
    return None


def _most_recent_assistant_content(messages: list[dict]) -> Optional[str]:
    """The most recent assistant message's text content, if any."""
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            return content
    return None


def cancel_pending_write(messages: list[dict]) -> None:
    """Deregister the preview behind the latest assistant message.

    Called on an explicit user cancellation so a later bare "yes" cannot
    replay the declined write from the registry.
    """
    content = _most_recent_assistant_content(messages)
    if content is None:
        return
    for preview_text in [p for p in _pending_writes if p in content]:
        _pending_writes.pop(preview_text, None)

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
_CANCEL = re.compile(
    r"^(?:"
    r"no(?:[,.!]?\s*(?:thanks?|thank\s+you|don'?t(?:\s+save)?|do\s+not(?:\s+save)?|"
    r"cancel|stop|not\s+now))?|"
    r"nope|nah|"
    r"cancel(?:\s+(?:that|it|this))?|"
    r"don'?t(?:\s+(?:save|do\s+it))?|"
    r"do\s+not(?:\s+save)?|"
    r"stop|"
    r"never\s*mind|"
    r"discard(?:\s+(?:it|that))?|"
    r"forget\s+it|"
    r"scratch\s+that|"
    r"abort|"
    r"not\s+now"
    r")\.?\s*$",
    re.IGNORECASE,
)
_CANCEL_PREFIX = re.compile(
    r"^(?:no|nope|nah|cancel|don'?t|do\s+not|stop|discard|abort|never\s*mind)\b",
    re.IGNORECASE,
)
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


def is_user_cancellation(message: str) -> bool:
    """Return True when the message declines/cancels a pending write."""
    text = message.strip()
    if not text:
        return False
    if _CANCEL.match(text):
        return True
    return bool(_CANCEL_PREFIX.search(text))


def parse_pending_write(messages: list[dict]) -> Optional[tuple[str, dict[str, Any]]]:
    """Read tool name and arguments from a live write preview.

    Only the most recent assistant message is considered: once any later
    assistant reply lands (a cancellation acknowledgement, an unrelated
    answer), the preview is stale and a bare "yes" must not replay it.

    The structured registry is authoritative; the text-parsing fallback
    only serves previews whose registration was lost (process restart).
    """
    content = _most_recent_assistant_content(messages)
    if content is None:
        return None

    registered = _lookup_pending_write(content)
    if registered is not None:
        return registered

    if PENDING_CONFIRMATION_MARKER not in content:
        return None
    return _parse_preview_text(content)


def _parse_preview_text(content: str) -> Optional[tuple[str, dict[str, Any]]]:
    """Legacy text parsing of a rendered preview (registry-loss fallback)."""
    if "Delete client" in content:
        client_id_match = _PENDING_CLIENT_ID.search(content)
        if client_id_match:
            return (
                "delete_client",
                {"client_id": client_id_match.group(1).strip()},
            )
        return None

    if "Delete note" in content:
        note_id_match = _PENDING_NOTE_ID.search(content)
        if note_id_match:
            return ("delete_client_note", {"note_id": int(note_id_match.group(1))})
        return None

    if "Update note" in content:
        note_id_match = _PENDING_NOTE_ID.search(content)
        content_match = _PENDING_NOTE_CONTENT.search(content)
        if not note_id_match or not content_match:
            return None
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
            return None
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
            return None
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
