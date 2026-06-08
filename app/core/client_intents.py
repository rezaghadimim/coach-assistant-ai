"""Detect client management commands and run them without relying on the LLM."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from app.core.confirmations import is_user_confirmation, parse_pending_write
from app.memory.store import MemoryStore

logger = logging.getLogger(__name__)

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
_ADD_AS_CLIENT = re.compile(
    r"(?:add|register)\s+(.+?)\s+as\s+(?:a\s+|another\s+)?(?:client|patient)"
    r"(?:\s+profile)?\s*$",
    re.IGNORECASE,
)
_CREATE_NAMED_CLIENT = re.compile(
    r"(?:add|create|register)\s+(?:a\s+new\s+|another\s+|new\s+|a\s+)?"
    r"(?:client|patient)\s+(?:named\s+|called\s+)?(.+?)(?:\s+profile)?\s*$",
    re.IGNORECASE,
)

_PREFIXES_TO_STRIP = re.compile(r"^(?:the|patient|client)\s+", re.IGNORECASE)
_PRONOUN_PLACEHOLDERS = frozenset(
    {"this", "that", "a", "an", "my", "your", "their", "our", "its"}
)


def _clean_client_ref(raw: str) -> str:
    return _PREFIXES_TO_STRIP.sub("", raw.strip()).strip(" .,?")


def _slug_client_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "client"


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


def detect_create_client(message: str) -> Optional[dict[str, str]]:
    """Return client_id and display name when the message registers a new client."""
    text = message.strip()
    if not text:
        return None

    name: Optional[str] = None
    for pattern in (_ADD_AS_CLIENT, _CREATE_NAMED_CLIENT):
        match = pattern.search(text)
        if match:
            name = _clean_client_ref(match.group(1))
            break

    if not name or name.lower() in _PRONOUN_PLACEHOLDERS:
        return None

    return {"client_id": _slug_client_id(name), "name": name}


def detect_confirm(message: str) -> bool:
    """Backward-compatible alias for the shared confirmation detector."""
    return is_user_confirmation(message)


def _extract_tool_payload(data: dict[str, Any]) -> Optional[tuple[str, dict[str, Any]]]:
    tool_name = data.get("tool") or data.get("name") or data.get("function")
    params = data.get("parameters") or data.get("arguments") or data.get("params")
    if isinstance(tool_name, str) and isinstance(params, dict):
        return tool_name, params
    return None


def _embedded_tool_json_candidates(content: str) -> list[str]:
    """Collect JSON substrings that may contain a text-based tool call."""
    candidates = [content.strip()]
    for match in re.finditer(r"\{[^{}]*\"tool\"\s*:", content):
        start = match.start()
        depth = 0
        for index in range(start, len(content)):
            char = content[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(content[start : index + 1])
                    break
    return candidates


def parse_text_tool_call(content: str) -> Optional[tuple[str, dict[str, Any]]]:
    """Parse tool calls some models emit as JSON text instead of native tool_calls."""
    stripped = content.strip()
    if not stripped:
        return None

    for candidate in _embedded_tool_json_candidates(stripped):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue

        payload = _extract_tool_payload(data)
        if payload:
            return payload

        error_text = data.get("error")
        if isinstance(error_text, str):
            for nested in _embedded_tool_json_candidates(error_text):
                try:
                    nested_data = json.loads(nested)
                except json.JSONDecodeError:
                    continue
                if isinstance(nested_data, dict):
                    payload = _extract_tool_payload(nested_data)
                    if payload:
                        return payload
    return None


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
    """Run a read-only client query directly. Returns None if not a lookup command.

    Tries fast regex patterns first, then falls back to the offline intent
    knowledge base. Returns ``None`` (deferring to the LLM) whenever neither is
    confident, or when a client-scoped intent does not name a known client.
    """
    from app.core.tools import execute_tool

    if detect_list_clients(message):
        logger.debug("client_intents: regex list_clients matched")
        return execute_tool("list_clients", {}, store)

    client_ref = detect_client_lookup(message)
    if client_ref:
        logger.debug("client_intents: regex lookup matched ref=%r", client_ref)
        return execute_tool("get_client_full", {"client_id": client_ref}, store)

    return _kb_client_query(message, store)


def _kb_client_query(message: str, store: MemoryStore) -> Optional[str]:
    """Knowledge-base fallback for read-only client queries."""
    from app.core.intent_kb import classify
    from app.core.tools import execute_tool

    match = classify(message)
    if match is None:
        logger.debug("client_intents: KB deferred (no confident intent)")
        return None

    if not match.requires_client:
        logger.debug(
            "client_intents: KB matched intent=%s score=%.2f", match.intent, match.score
        )
        return execute_tool(match.tool, {}, store)

    client_id = detect_client_mention(message, store)
    if client_id is None:
        # Confident about the intent but cannot tie it to a known client;
        # defer to the LLM rather than guessing.
        logger.debug(
            "client_intents: KB intent=%s but no known client mentioned; deferring",
            match.intent,
        )
        return None

    params: dict[str, Any] = {"client_id": client_id}
    if match.note_type:
        params["note_type"] = match.note_type
    logger.debug(
        "client_intents: KB matched intent=%s score=%.2f client=%s note_type=%s",
        match.intent,
        match.score,
        client_id,
        match.note_type,
    )
    return execute_tool(match.tool, params, store)


def try_direct_client_action(
    message: str,
    store: MemoryStore,
    messages: Optional[list[dict]] = None,
) -> Optional[str]:
    """Run client read/write commands directly. Returns None if not a known command."""
    from app.core.tools import execute_tool

    history = messages or []

    if is_user_confirmation(message):
        pending = parse_pending_write(history)
        if pending:
            tool_name, params = pending
            return execute_tool(tool_name, {**params, "confirmed": True}, store)

    create_args = detect_create_client(message)
    if create_args:
        return execute_tool("create_client", create_args, store)

    text_tool = parse_text_tool_call(message)
    if text_tool:
        tool_name, params = text_tool
        return execute_tool(tool_name, params, store)

    return try_direct_client_query(message, store)
