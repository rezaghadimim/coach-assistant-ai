"""Detect client management commands and run them without relying on the LLM."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

from app.core.confirmations import (
    is_user_cancellation,
    is_user_confirmation,
    parse_pending_write,
)
from app.core.observability import log_step
from app.core.tool_json import (
    looks_like_malformed_tool_call,
    parse_text_tool_call,
)
from app.memory.store import MemoryStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClientActionResult:
    """Fast-path client command result with optional routing metadata for formatting.

    ``status`` mirrors :class:`app.core.tools.ToolOutcome.status`
    (preview/ok/error/info); ``None`` for replies not produced by a tool.
    """

    reply: str
    tool: str | None = None
    hint: str | None = None
    status: str | None = None

    @property
    def is_terminal(self) -> bool:
        """True when the reply must be surfaced verbatim (no lookup formatting)."""
        return self.status in ("preview", "ok", "error")


def _from_outcome(
    outcome, *, tool: str | None = None, hint: str | None = None
) -> ClientActionResult:
    """Wrap a ToolOutcome into a ClientActionResult carrying its status."""
    return ClientActionResult(outcome.text, tool=tool, hint=hint, status=outcome.status)


# Surfaced verbatim (status "ok") when the coach declines a pending write preview.
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
    r"(?:email|phone|mobile|cell|cellphone|number|profile|detail|details|info|information|data)",
    re.IGNORECASE,
)
_LIST_CLIENTS = re.compile(
    r"(?:who\s+are|list|show)\s+(?:my\s+)?(?:clients?|patients?)",
    re.IGNORECASE,
)
_ADD_AS_CLIENT = re.compile(
    r"(?:add|register)\s+(.+?)\s+as\s+(?:a\s+(?:new\s+)?|another\s+)?(?:client|patient)"
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
_PHONE_SET = re.compile(
    r"(?:update|set|change|save)\s+(.+?)(?:'s|'s)\s+phone(?:\s+number)?\s+(?:to\s+be|to|as)\s+([\d\s\-\+\(\)\.]+)",
    re.IGNORECASE,
)
_EMAIL_SET = re.compile(
    r"(?:update|set|change|save)\s+(.+?)(?:'s|'s)\s+email(?:\s+address)?\s+(?:to\s+be|to|as)\s+(\S+@\S+)",
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
_PHONE_FOR = re.compile(
    r"(?:add|set|update|change)\s+phone(?:\s+number)?\s+for\s+(.+?)\s+(?:to\s+)?([\d\s\-\+\(\)\.]+)",
    re.IGNORECASE,
)
_PHONE_FOR_REVERSE = re.compile(
    r"(?:add|set|update|change)\s+phone(?:\s+number)?\s+(?:to\s+)?([\d\s\-\+\(\)\.]+)\s+for\s+(.+?)\s*$",
    re.IGNORECASE,
)
_EMAIL_FOR = re.compile(
    r"(?:add|set|update|change)\s+email(?:\s+address)?\s+for\s+(.+?)\s+(?:to\s+be\s+|to\s+)?(\S+@\S+)",
    re.IGNORECASE,
)
_EMAIL_FOR_REVERSE = re.compile(
    r"(?:add|set|update|change)\s+email(?:\s+address)?\s+(?:to\s+be\s+|to\s+)?(\S+@\S+)\s+for\s+(.+?)\s*$",
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

# A message that clearly mutates a profile field but that the deterministic
# extractors above could not parse. Used as a last-resort guard so such
# messages defer to the LLM tool loop instead of leaking into the read-only
# query path (which would wrongly return a profile card). Intentionally broad
# on the verb side and anchored on a profile-field keyword to avoid catching
# pure coaching talk.
_PROFILE_WRITE_INTENT = re.compile(
    r"\b(?:update|set|change|modify|edit|make|assign|correct|fix|"
    r"save|store|put|record|register)\b"
    r"[^.!?]{0,40}?\b(?:e-?mail|phone|mobile|number|age|name|"
    r"occupation|job|profession|background|address|birthday|dob|"
    r"date\s+of\s+birth)\b",
    re.IGNORECASE,
)

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


def looks_like_unhandled_profile_write(message: str) -> bool:
    """True when the message clearly edits a profile field.

    Used to keep mutation requests away from the read-only query path when the
    deterministic extractors could not parse them: such messages should defer
    to the LLM (which extracts params from arbitrary phrasing) rather than
    return a profile card.
    """
    return bool(_PROFILE_WRITE_INTENT.search(message.strip()))


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
        (_PHONE_SET, "phone", lambda value: value.strip()),
        (_EMAIL_SET, "email", lambda value: value.rstrip(".").strip()),
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

    for pattern, client_group, value_group, field, transform in (
        (_AGE_FOR, 1, 2, "age", int),
        (_AGE_FOR_REVERSE, 2, 1, "age", int),
        (_PHONE_FOR, 1, 2, "phone", lambda value: value.strip()),
        (_PHONE_FOR_REVERSE, 2, 1, "phone", lambda value: value.strip()),
        (_EMAIL_FOR, 1, 2, "email", lambda value: value.rstrip(".").strip()),
        (_EMAIL_FOR_REVERSE, 2, 1, "email", lambda value: value.rstrip(".").strip()),
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
            **{field: transform(match.group(value_group))},
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


_SIMPLE_GREETING = re.compile(
    r"^(?:hi|hello|hey|howdy|greetings|good\s+(?:morning|afternoon|evening))"
    r"(?:\s+(?:there|coach|everyone|all))?"
    r"[!.,?\s]*$",
    re.IGNORECASE,
)

SIMPLE_GREETING_REPLY = (
    "Hello! I'm Coach Assistant AI — here to help you with client notes, "
    "session prep, and coaching strategies. What would you like to work on today?"
)


def is_simple_greeting(message: str) -> bool:
    """Return True for short social openers that need no tools or LLM routing."""
    return bool(_SIMPLE_GREETING.match(message.strip()))


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


# A "profile" lookup that the reranker can confuse with the story/background
# note cluster (intent_kb: "show me the client's background story"). When the
# coach asks for a *profile* and does not mention story/background/notes, the
# intent is the profile card (get_client), never story notes.
_PROFILE_WORD = re.compile(r"\bprofile\b", re.IGNORECASE)
_NOTE_SIGNAL = re.compile(r"\b(?:story|stories|background|notes?)\b", re.IGNORECASE)


def _looks_like_profile_lookup(message: str) -> bool:
    """True when the message asks for a profile card, not notes/story content."""
    text = message.strip()
    return bool(_PROFILE_WORD.search(text)) and not _NOTE_SIGNAL.search(text)


_UPDATE_NOTE_ID = re.compile(
    r"(?:update|edit|change|revise|fix)\s+note\s+(\d+)",
    re.IGNORECASE,
)
_DELETE_NOTE_ID = re.compile(
    r"(?:delete|remove|drop)\s+note\s+(\d+)",
    re.IGNORECASE,
)


def _tool_router_action(message: str, store: MemoryStore) -> ClientActionResult | None:
    """Use the tool router to classify and execute the best-matching tool.

    Called after regex profile/create detection and before :func:`try_direct_client_query`.
    Returns ``None`` when the router is not confident or params cannot be extracted.
    """
    from app.core.tool_router import classify_tool
    from app.core.tools import execute_tool_outcome

    match = classify_tool(message)
    if match is None:
        return None

    tool = match.tool
    hint = match.hint or ""
    log_step(logger, "tool_router.action", "executing", tool=tool,
             score=match.score, backend=match.backend, hint=hint or None,
             level=logging.DEBUG)

    if tool == "list_clients":
        return _from_outcome(
            execute_tool_outcome("list_clients", {}, store),
            tool=tool,
            hint=match.hint,
        )

    if tool == "create_client":
        # Router says profile update; delegate to existing param extractors.
        profile_args = detect_profile_update(message, store)
        if profile_args:
            return _from_outcome(
                execute_tool_outcome("create_client", profile_args, store),
                tool=tool,
                hint=match.hint,
            )
        create_args = detect_create_client(message)
        if create_args:
            return _from_outcome(
                execute_tool_outcome("create_client", create_args, store),
                tool=tool,
                hint=match.hint,
            )
        # Confident about the tool but cannot extract params → LLM handles it.
        return None

    if tool in ("get_client", "get_client_full"):
        client_ref = detect_client_lookup(message)
        if client_ref:
            return _from_outcome(
                execute_tool_outcome(tool, {"client_id": client_ref}, store),
                tool=tool,
                hint=match.hint,
            )
        client_id = detect_client_mention(message, store)
        if client_id:
            return _from_outcome(
                execute_tool_outcome(tool, {"client_id": client_id}, store),
                tool=tool,
                hint=match.hint,
            )
        return None

    if tool == "list_client_notes":
        # The reranker confuses "profile" with the story/background note cluster.
        # A profile lookup ("Show me Ali's profile") must return the profile card,
        # not empty story notes, so override to get_client before executing.
        if _looks_like_profile_lookup(message):
            client_ref = detect_client_lookup(message) or detect_client_mention(
                message, store
            )
            if client_ref:
                log_step(logger, "tool_router.action", "override",
                         from_tool=tool, to_tool="get_client",
                         reason="profile_lookup")
                return _from_outcome(
                    execute_tool_outcome("get_client", {"client_id": client_ref}, store),
                    tool="get_client",
                    hint="profile",
                )
        client_id = detect_client_mention(message, store)
        if client_id is None:
            return None
        params: dict[str, Any] = {"client_id": client_id}
        # Extract note_type from hint, e.g. "note_type:goal"
        if hint.startswith("note_type:"):
            note_type = hint.split(":", 1)[1]
            params["note_type"] = note_type
        return _from_outcome(
            execute_tool_outcome("list_client_notes", params, store),
            tool=tool,
            hint=match.hint,
        )

    if tool == "update_client_note":
        id_match = _UPDATE_NOTE_ID.search(message)
        if id_match:
            return _from_outcome(
                execute_tool_outcome(
                    "update_client_note",
                    {"note_id": int(id_match.group(1)), "content": message},
                    store,
                )
            )
        return None

    if tool == "delete_client_note":
        id_match = _DELETE_NOTE_ID.search(message)
        if id_match:
            return _from_outcome(
                execute_tool_outcome(
                    "delete_client_note", {"note_id": int(id_match.group(1))}, store
                )
            )
        return None

    if tool == "delete_client":
        client_ref = detect_client_lookup(message)
        if client_ref:
            return _from_outcome(
                execute_tool_outcome("delete_client", {"client_id": client_ref}, store)
            )
        client_id = detect_client_mention(message, store)
        if client_id:
            return _from_outcome(
                execute_tool_outcome("delete_client", {"client_id": client_id}, store)
            )
        return None

    # add_client_note and any unknown tool: defer to LLM for param extraction.
    return None


def try_direct_client_query_with_meta(
    message: str, store: MemoryStore
) -> ClientActionResult | None:
    """Run a read-only client query directly, with routing metadata when known."""
    from app.core.tools import execute_tool_outcome

    if detect_list_clients(message):
        log_step(logger, "intent.regex", "hit", pattern="list_clients")
        return _from_outcome(
            execute_tool_outcome("list_clients", {}, store), tool="list_clients"
        )

    client_ref = detect_client_lookup(message)
    if client_ref:
        log_step(logger, "intent.regex", "hit", pattern="client_lookup", ref=client_ref)
        return _from_outcome(
            execute_tool_outcome("get_client_full", {"client_id": client_ref}, store),
            tool="get_client_full",
        )

    return _kb_client_query_with_meta(message, store)


def _kb_client_query_with_meta(message: str, store: MemoryStore) -> ClientActionResult | None:
    """Knowledge-base fallback for read-only client queries."""
    from app.core.intent_kb import classify
    from app.core.tools import execute_tool_outcome

    match = classify(message)
    if match is None:
        log_step(logger, "intent_kb", "miss", level=logging.DEBUG)
        return None

    if not match.requires_client:
        log_step(logger, "intent_kb", "hit", intent=match.intent, score=match.score)
        return _from_outcome(execute_tool_outcome(match.tool, {}, store), tool=match.tool)

    client_id = detect_client_mention(message, store)
    if client_id is None:
        log_step(logger, "intent_kb", "defer", level=logging.DEBUG,
                 intent=match.intent, reason="no_client_mentioned")
        return None

    params: dict[str, Any] = {"client_id": client_id}
    if match.note_type:
        params["note_type"] = match.note_type
    log_step(logger, "intent_kb", "hit", intent=match.intent,
             score=match.score, client=client_id, note_type=match.note_type)
    hint = f"note_type:{match.note_type}" if match.note_type else None
    return _from_outcome(
        execute_tool_outcome(match.tool, params, store),
        tool=match.tool,
        hint=hint,
    )


def try_direct_client_query(message: str, store: MemoryStore) -> Optional[str]:
    """Run a read-only client query directly. Returns None if not a lookup command.

    Tries fast regex patterns first, then falls back to the offline intent
    knowledge base. Returns ``None`` (deferring to the LLM) whenever neither is
    confident, or when a client-scoped intent does not name a known client.
    """
    result = try_direct_client_query_with_meta(message, store)
    return result.reply if result is not None else None


def try_direct_client_action_with_meta(
    message: str,
    store: MemoryStore,
    messages: Optional[list[dict]] = None,
) -> ClientActionResult | None:
    """Run client read/write commands directly, with routing metadata when known."""
    from app.core.tools import execute_tool_outcome

    history = messages or []

    pending = parse_pending_write(history)
    if pending:
        if is_user_cancellation(message):
            log_step(logger, "confirmation", "cancel")
            return ClientActionResult(_CANCEL_REPLY, status="ok")
        if is_user_confirmation(message):
            tool_name, params = pending
            log_step(logger, "confirmation", "confirm", tool=tool_name)
            return _from_outcome(
                execute_tool_outcome(tool_name, {**params, "confirmed": True}, store)
            )
        log_step(logger, "confirmation", "none", level=logging.DEBUG)

    profile_args = detect_profile_update(message, store)
    if profile_args:
        log_step(logger, "intent.regex", "hit", pattern="profile_update",
                 client=profile_args.get("client_id", "?"))
        return _from_outcome(execute_tool_outcome("create_client", profile_args, store))

    create_args = detect_create_client(message)
    if create_args:
        log_step(logger, "intent.regex", "hit", pattern="create_client",
                 client=create_args.get("client_id", "?"))
        return _from_outcome(execute_tool_outcome("create_client", create_args, store))

    text_tool = parse_text_tool_call(message)
    if text_tool:
        from app.core.tools import sanitize_write_confirmation

        tool_name, params = text_tool
        log_step(logger, "intent.regex", "hit", pattern="text_tool_call", tool=tool_name)
        params = sanitize_write_confirmation(tool_name, params, message)
        return _from_outcome(execute_tool_outcome(tool_name, params, store))

    log_step(logger, "intent.regex", "miss", level=logging.DEBUG)

    router_result = _tool_router_action(message, store)
    if router_result is not None:
        return router_result

    if looks_like_unhandled_profile_write(message):
        log_step(logger, "intent.profile_write_guard", "defer", level=logging.DEBUG)
        return None

    return try_direct_client_query_with_meta(message, store)


def try_direct_client_action(
    message: str,
    store: MemoryStore,
    messages: Optional[list[dict]] = None,
) -> Optional[str]:
    """Run client read/write commands directly. Returns None if not a known command."""
    result = try_direct_client_action_with_meta(message, store, messages)
    return result.reply if result is not None else None
