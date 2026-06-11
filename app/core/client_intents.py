"""Detect client management commands and run them without relying on the LLM."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from app.core.confirmations import (
    is_user_cancellation,
    is_user_confirmation,
    parse_pending_write,
)
from app.memory.store import MemoryStore

logger = logging.getLogger(__name__)

# Returned (with a recognized status prefix so the LLM layer surfaces it
# verbatim) when the coach declines a pending write preview.
_CANCEL_REPLY = (
    "✅ Okay, I won't save that — nothing has been changed. "
    "Let me know if you'd like to adjust the details or work on something else."
)

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
_PROFILE_CONTEXT_SUFFIX = re.compile(r"\s+profile\s*$", re.IGNORECASE)
_AGE_IS = re.compile(
    r"^(.+?)\s+is\s+(\d{1,3})\s+years?\s+old\.?\s*$",
    re.IGNORECASE,
)
_AGE_POSSESSIVE = re.compile(
    r"^(.+?)(?:'s|'s)\s+age\s+is\s+(\d{1,3})\b",
    re.IGNORECASE,
)
_AGE_SET = re.compile(
    r"(?:update|set|change|save)\s+(.+?)(?:'s|'s)\s+age\s+(?:to|as)\s+(\d{1,3})\b",
    re.IGNORECASE,
)
_AGE_FOR = re.compile(
    r"(?:add|set|update|change)\s+age\s+for\s+(.+?)\s+(?:to\s+)?(\d{1,3})\b",
    re.IGNORECASE,
)
_AGE_FOR_REVERSE = re.compile(
    r"(?:add|set|update|change)\s+age\s+(?:to\s+)?(\d{1,3})\s+for\s+(.+?)\s*$",
    re.IGNORECASE,
)
_EMAIL_POSSESSIVE = re.compile(
    r"^(.+?)(?:'s|'s)\s+email\s+is\s+(\S+@\S+)\.?\s*$",
    re.IGNORECASE,
)
_PHONE_POSSESSIVE = re.compile(
    r"^(.+?)(?:'s|'s)\s+phone(?:\s+number)?\s+is\s+([\d\s\-\+\(\)\.]+)\.?\s*$",
    re.IGNORECASE,
)
_AGE_ONLY = re.compile(r"^(\d{1,3})\s+years?\s+old\.?\s*$", re.IGNORECASE)

_PREFIXES_TO_STRIP = re.compile(r"^(?:the|patient|client)\s+", re.IGNORECASE)
_PRONOUN_PLACEHOLDERS = frozenset(
    {"this", "that", "a", "an", "my", "your", "their", "our", "its"}
)
_EXPLICIT_NOTE_SAVE = re.compile(
    r"\b(?:"
    r"note\s+that|save\s+(?:a\s+)?note|document\s+that|record\s+that|"
    r"add\s+(?:a\s+)?note|write\s+(?:this|that|it)\s+down|log\s+that|"
    r"save\s+(?:a\s+)?(?:goal|decision|story|progress)|"
    r"document\s+(?:the|that|this)|note\s+(?:for|about)"
    r")\b",
    re.IGNORECASE,
)
_COACHING_ADVICE = re.compile(
    r"(?:"
    r"\?\s*$|"
    r"\b(?:"
    r"want\s+to\s+know|how\s+(?:can|do|should|would)|what\s+(?:should|would|can)|"
    r"tell\s+me\s+(?:how|what|one|a)|give\s+me\s+(?:a\s+)?(?:way|tip|idea|suggestion|advice)|"
    r"one\s+way\s+(?:to|about)|help\s+me\s+(?:with|understand)|"
    r"suggest\s+(?:a|some|any)|recommend\s+(?:a|some|any)|"
    r"what\s+(?:is|are)\s+(?:some|a\s+good)|"
    r"in\s+general\s+(?:i\s+)?(?:want|need|would\s+like)"
    r")\b"
    r")",
    re.IGNORECASE,
)

NOTE_WRITE_MISFIRE_GUIDANCE = (
    "⚠️ The coach is asking for coaching advice or guidance, not requesting "
    "that you save a note. Do not call add_client_note. Answer in plain "
    "language with specific, actionable coaching suggestions."
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


def _strip_profile_context(text: str) -> str:
    return _PROFILE_CONTEXT_SUFFIX.sub("", text.strip()).strip(" .")


def _profile_update_args(
    client_ref: str,
    store: MemoryStore,
    *,
    message: str = "",
    **fields: Any,
) -> dict[str, Any]:
    from app.core.tools import _fuzzy_resolve_client_id, _resolve_client_id

    resolved_id = _resolve_client_id(store, client_ref)
    if resolved_id is None:
        resolved_id = _fuzzy_resolve_client_id(store, client_ref)
    if resolved_id is None and message.strip():
        resolved_id = detect_client_mention(message, store)
    client_id = resolved_id or client_ref.strip()
    existing = store.get_user(client_id)
    name = (existing or {}).get("name") or client_ref.strip()
    return {"client_id": client_id, "name": name, **fields}


def detect_profile_update(
    message: str,
    store: MemoryStore,
) -> Optional[dict[str, Any]]:
    """Return create_client args when the message updates a profile field."""
    text = _strip_profile_context(message.strip())
    if not text:
        return None

    for pattern, field, transform in (
        (_AGE_IS, "age", int),
        (_AGE_POSSESSIVE, "age", int),
        (_AGE_SET, "age", int),
        (_EMAIL_POSSESSIVE, "email", str),
        (_PHONE_POSSESSIVE, "phone", lambda value: value.strip()),
    ):
        match = pattern.search(text)
        if not match:
            continue
        client_ref = _clean_client_ref(match.group(1))
        if not client_ref or client_ref.lower() in _PRONOUN_PLACEHOLDERS:
            continue
        return _profile_update_args(
            client_ref,
            store,
            message=text,
            **{field: transform(match.group(2))},
        )

    for pattern, client_group, age_group in (
        (_AGE_FOR, 1, 2),
        (_AGE_FOR_REVERSE, 2, 1),
    ):
        match = pattern.search(text)
        if not match:
            continue
        client_ref = _clean_client_ref(match.group(client_group))
        if not client_ref or client_ref.lower() in _PRONOUN_PLACEHOLDERS:
            continue
        return _profile_update_args(
            client_ref,
            store,
            message=text,
            age=int(match.group(age_group)),
        )

    return None


def profile_update_from_add_note(
    arguments: dict[str, Any],
    store: MemoryStore,
) -> Optional[dict[str, Any]]:
    """When add_client_note carries profile data, return create_client args instead."""
    content = arguments.get("content", "")
    if not isinstance(content, str) or not content.strip():
        return None

    parsed = detect_profile_update(content, store)
    if parsed is not None:
        return parsed

    client_ref = arguments.get("client_id", "")
    if not isinstance(client_ref, str) or not client_ref.strip():
        return None

    age_match = _AGE_ONLY.match(content.strip())
    if age_match:
        return _profile_update_args(
            client_ref,
            store,
            message=content,
            age=int(age_match.group(1)),
        )
    return None


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


def is_coaching_advice_request(message: str) -> bool:
    """Return True when the coach is asking for guidance, not saving a note."""
    text = message.strip()
    if not text:
        return False
    if _EXPLICIT_NOTE_SAVE.search(text):
        return False
    return bool(_COACHING_ADVICE.search(text))


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


_UPDATE_NOTE_ID = re.compile(
    r"(?:update|edit|change|revise|fix)\s+note\s+(\d+)",
    re.IGNORECASE,
)
_DELETE_NOTE_ID = re.compile(
    r"(?:delete|remove|drop)\s+note\s+(\d+)",
    re.IGNORECASE,
)


def _tool_router_action(message: str, store: MemoryStore) -> Optional[str]:
    """Use the tool router to classify and execute the best-matching tool.

    Called after regex profile/create detection and before :func:`try_direct_client_query`.
    Returns ``None`` when the router is not confident or params cannot be extracted.
    """
    from app.core.tool_router import classify_tool
    from app.core.tools import execute_tool

    match = classify_tool(message)
    if match is None:
        return None

    tool = match.tool
    hint = match.hint or ""
    logger.debug(
        "client_intents: tool_router matched tool=%s score=%.2f hint=%r backend=%s",
        tool,
        match.score,
        hint,
        match.backend,
    )

    if tool == "list_clients":
        return execute_tool("list_clients", {}, store)

    if tool == "create_client":
        # Router says profile update; delegate to existing param extractors.
        profile_args = detect_profile_update(message, store)
        if profile_args:
            return execute_tool("create_client", profile_args, store)
        create_args = detect_create_client(message)
        if create_args:
            return execute_tool("create_client", create_args, store)
        # Confident about the tool but cannot extract params → LLM handles it.
        return None

    if tool in ("get_client", "get_client_full"):
        client_ref = detect_client_lookup(message)
        if client_ref:
            return execute_tool(tool, {"client_id": client_ref}, store)
        client_id = detect_client_mention(message, store)
        if client_id:
            return execute_tool(tool, {"client_id": client_id}, store)
        return None

    if tool == "list_client_notes":
        client_id = detect_client_mention(message, store)
        if client_id is None:
            return None
        params: dict[str, Any] = {"client_id": client_id}
        # Extract note_type from hint, e.g. "note_type:goal"
        if hint.startswith("note_type:"):
            note_type = hint.split(":", 1)[1]
            params["note_type"] = note_type
        return execute_tool("list_client_notes", params, store)

    if tool == "update_client_note":
        id_match = _UPDATE_NOTE_ID.search(message)
        if id_match:
            return execute_tool("update_client_note", {"note_id": int(id_match.group(1)), "content": message}, store)
        return None

    if tool == "delete_client_note":
        id_match = _DELETE_NOTE_ID.search(message)
        if id_match:
            return execute_tool("delete_client_note", {"note_id": int(id_match.group(1))}, store)
        return None

    if tool == "delete_client":
        client_ref = detect_client_lookup(message)
        if client_ref:
            return execute_tool("delete_client", {"client_id": client_ref}, store)
        client_id = detect_client_mention(message, store)
        if client_id:
            return execute_tool("delete_client", {"client_id": client_id}, store)
        return None

    # add_client_note and any unknown tool: defer to LLM for param extraction.
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

    pending = parse_pending_write(history)
    if pending:
        # Resolve the pending write first so a decline cancels it instead of
        # falling through to the LLM, which would re-propose the same preview.
        if is_user_cancellation(message):
            logger.debug("client_intents: pending write cancelled by user")
            return _CANCEL_REPLY
        if is_user_confirmation(message):
            tool_name, params = pending
            return execute_tool(tool_name, {**params, "confirmed": True}, store)

    profile_args = detect_profile_update(message, store)
    if profile_args:
        return execute_tool("create_client", profile_args, store)

    create_args = detect_create_client(message)
    if create_args:
        return execute_tool("create_client", create_args, store)

    text_tool = parse_text_tool_call(message)
    if text_tool:
        tool_name, params = text_tool
        return execute_tool(tool_name, params, store)

    router_result = _tool_router_action(message, store)
    if router_result is not None:
        return router_result

    return try_direct_client_query(message, store)
