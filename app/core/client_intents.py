"""Detect client lookup commands and run them without relying on the LLM."""

from __future__ import annotations

import re
from typing import Optional

from app.memory.store import MemoryStore

_POSSESSIVE_LOOKUP = re.compile(
    r"(?:get|show|give|fetch|retrieve|pull|tell)\s+(?:me\s+)?"
    r"(?:the\s+)?(.+?)(?:'s|'s)\s+"
    r"(?:detail|details|profile|info|information|data|record|notes?)",
    re.IGNORECASE,
)
_ABOUT_LOOKUP = re.compile(
    r"(?:get|show|give|fetch|retrieve|pull|tell)\s+(?:me\s+)?"
    r"(?:all\s+)?(?:the\s+)?(?:detail|details|profile|info|information|data|record|everything)"
    r"\s+(?:about|for|on)\s+(.+?)(?:\s+patient)?\s*$",
    re.IGNORECASE,
)
_FIELD_LOOKUP = re.compile(
    r"(?:what\s+is|what's|show)\s+(.+?)(?:'s|'s)\s+"
    r"(?:email|phone|profile|detail|details|info|information|data)",
    re.IGNORECASE,
)
_LIST_CLIENTS = re.compile(
    r"(?:who\s+are|list|show)\s+(?:my\s+)?(?:clients?|patients?)",
    re.IGNORECASE,
)

_PREFIXES_TO_STRIP = re.compile(r"^(?:the|patient|client)\s+", re.IGNORECASE)
_PRONOUN_PLACEHOLDERS = frozenset(
    {"this", "that", "a", "an", "my", "your", "their", "our", "its"}
)


def _clean_client_ref(raw: str) -> str:
    return _PREFIXES_TO_STRIP.sub("", raw.strip()).strip(" .,?")


def detect_client_lookup(message: str) -> Optional[str]:
    """Return a client id or display name when the message is a profile lookup."""
    text = message.strip()
    if not text:
        return None

    for pattern in (_POSSESSIVE_LOOKUP, _ABOUT_LOOKUP, _FIELD_LOOKUP):
        match = pattern.search(text)
        if match:
            client_ref = _clean_client_ref(match.group(1))
            if client_ref and client_ref.lower() not in _PRONOUN_PLACEHOLDERS:
                return client_ref
    return None


def detect_list_clients(message: str) -> bool:
    return bool(_LIST_CLIENTS.search(message.strip()))


def _word_boundary_pattern(term: str) -> re.Pattern[str]:
    return re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)


def detect_client_mention(message: str, store: MemoryStore) -> Optional[str]:
    """Return a client id when the message mentions a known client by name or id."""
    text = message.strip()
    if not text:
        return None

    candidates: list[tuple[str, str]] = []
    for user in store.list_users():
        user_id = user["user_id"]
        name = (user.get("name") or "").strip()
        candidates.append((user_id, user_id))
        if name:
            candidates.append((name, user_id))

    # Prefer longer names so "Ali Reza" wins over "Ali".
    candidates.sort(key=lambda pair: len(pair[0]), reverse=True)
    for term, resolved_id in candidates:
        if _word_boundary_pattern(term).search(text):
            return resolved_id
    return None


def try_direct_client_query(message: str, store: MemoryStore) -> Optional[str]:
    """Run a read-only client query directly. Returns None if not a lookup command."""
    from app.core.tools import execute_tool

    if detect_list_clients(message):
        return execute_tool("list_clients", {}, store)

    client_ref = detect_client_lookup(message)
    if client_ref:
        return execute_tool("get_client_full", {"client_id": client_ref}, store)

    return None
