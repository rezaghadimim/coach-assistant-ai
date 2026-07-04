"""LLM response formatter — optional human-friendly presentation layer.

When ``RESPONSE_FORMATTER_ENABLED=true``, fast-path data replies (raw tool
output wrapped in the deterministic template) are passed through a compact LLM
call that rephrases the data naturally and concisely.

Design constraints:
- The LLM decides **how** to present the data; the fast path decides **what** to fetch.
- PII validation runs after formatting: every email address and phone number
  found in the source data must appear verbatim in the formatted reply.
  On any validation failure or LLM error the deterministic template is returned.
- Only read replies are formatted.  Write previews (⏳), outcomes (✅/❌), and
  empty strings are passed through unchanged.
- Gated by ``settings.response_formatter_enabled`` (default ``True``).
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from app.core.config import settings
from app.core.observability import log_step

logger = logging.getLogger(__name__)

# Prefix used by _format_direct_lookup_reply to wrap successful tool results.
# Stripped before sending raw data to the LLM formatter so it doesn't see the
# mechanical header.
_DATA_REPLY_PREFIX = "Here are the details on file:\n\n"

# Patterns used to extract PII tokens that must survive the formatting pass.
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
# Phone candidates: formatted numbers (+, spaces, dashes, parens) or bare 7–15 digit runs.
_PHONE_FORMATTED_RE = re.compile(
    r"(?<!\d)(?:\+|00)?[\d][\d\s\-\(\)\./]{5,}[\d](?!\d)"
)
_PHONE_BARE_RE = re.compile(r"(?<!\d)\d{7,15}(?!\d)")
# ISO-style dates (e.g. note timestamps "2026-05-20") look phone-shaped to the
# patterns above; mask them out before extraction so they are not treated as PII.
_DATE_RE = re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b")

_TABLE_INTENT = re.compile(
    r"\b(?:table|tabular|spreadsheet|grid|matrix|columns?)\b",
    re.IGNORECASE,
)
_LIST_CLIENT_LINE = re.compile(
    r"^\s*-?\s*(?P<name>.+?)\s+\(ID:\s*(?P<id>[^,)]+),\s*Email:\s*(?P<email>.+?)\)\s*$",
    re.MULTILINE,
)
_PROFILE_FIELD_LINE = re.compile(r"^([A-Za-z][A-Za-z ]*): (.+)$", re.MULTILINE)
_NOTE_HEADER_LINE = re.compile(
    r"^- \[(?P<note_type>[A-Z]+)\](?: (?P<title>[^\(\n]+?))?\s*\((?P<date>[^)]+)\)\s*$"
)

# Extra LLM guidance appended per tool when deterministic formatting does not apply.
_FORMATTER_TOOL_HINTS: dict[str, str] = {
    "list_client_notes": (
        "Notes list → numbered list with type labels; keep dates verbatim."
    ),
    "list_clients": (
        "Multi-client list → warm sentence or bullets unless a table was requested."
    ),
    "get_client": "Single-field profile answers → one short sentence with that field only.",
    "get_client_full": (
        "Full-profile requests → email and phone verbatim when present, plus key notes "
        "in 2–4 sentences."
    ),
}

# Router hints like ``profile:email`` map to profile field labels in raw tool output.
_PROFILE_HINT_LABELS: dict[str, str] = {
    "profile:email": "Email",
    "profile:phone": "Phone",
    "profile:age": "Age",
    "profile:name": "Name",
    "profile:background": "Background",
    "profile:occupation": "Occupation",
}

_FORMATTER_SYSTEM_PROMPT = """\
You are a data presentation assistant for a life-coaching app.
Rephrase raw client database output as a short, natural reply to the coach's question.

Rules (STRICT):
- Answer ONLY what the coach asked. Single-field questions get one short sentence with that field only.
- Full-profile requests ("everything about X", "full profile") must include email and phone verbatim when present in the raw data, plus key notes in 2–4 sentences.
- Multi-client lists ("who are my clients?", "give me all clients") → a warm sentence or compact bullet list, NOT a markdown table, unless the coach asked for a table.
- Table requests ("in a table", "tabular") → a clean markdown table with only the columns requested.
- NEVER invent, omit, or paraphrase contact details (emails, phone numbers, client IDs) that you include.
- NEVER add follow-up questions, coaching advice, or meta-commentary about your instructions (no "Note:", no explaining what you left out).
- NEVER produce JSON, XML, or fenced code blocks. Markdown tables are allowed only when a table was requested.
- If a value is "(not set)", say it is not recorded yet.

Examples (follow this style exactly — output only the reply line, nothing else):

Coach: What is Ali's email?
Reply: Ali's email is ali@example.com.

Coach: What is Leila's age?
Reply: Leila is 35 years old.

Coach: Who are my clients?
Reply: You have two clients: Ali Hassan and Sara Karimi.

Coach: Show Sara's goals
Reply: Sara's goals are to complete a leadership certification by end of Q3 and start her own consulting practice within 12 months.

Coach: Get Ali's full profile
Reply: Ali Hassan is a 32-year-old Software Engineer (ali@example.com). He was referred by the corporate wellness programme, completed the time-management module on 2026-05-20, and aims to become a team lead within six months.
"""


def is_formattable(reply: str) -> bool:
    """Return True when *reply* is a raw data lookup result eligible for LLM formatting.

    Only replies produced by :func:`~app.core.llm._format_direct_lookup_reply`
    qualify — they start with the deterministic template prefix.  Write
    previews, error strings, greetings, and scope refusals are excluded.
    """
    return bool(reply) and reply.startswith(_DATA_REPLY_PREFIX)


def wants_table_format(message: str) -> bool:
    """Return True when the coach asked for tabular output."""
    return bool(_TABLE_INTENT.search(message.strip()))


def _display_value(value: str) -> str:
    """Normalize a field value for table display."""
    return "" if value.strip() in ("(not set)", "(none)", "none") else value.strip()


def _format_registered_clients_table(raw_data: str) -> Optional[str]:
    """Build a markdown table from ``list_clients`` tool output, or ``None``."""
    if "Registered clients:" not in raw_data:
        return None

    rows: list[tuple[str, str, str]] = []
    for match in _LIST_CLIENT_LINE.finditer(raw_data):
        rows.append(
            (
                match.group("name").strip(),
                match.group("id").strip(),
                _display_value(match.group("email")),
            )
        )
    if not rows:
        return None

    lines = [
        "| Name | ID | Email |",
        "| --- | --- | --- |",
    ]
    for name, client_id, email in rows:
        lines.append(f"| {name} | {client_id} | {email} |")
    return "\n".join(lines)


def _format_profile_fields_table(raw_data: str) -> Optional[str]:
    """Build a two-column table from single-client key-value profile output."""
    fields: list[tuple[str, str]] = []
    for line in raw_data.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _PROFILE_FIELD_LINE.match(stripped)
        if match:
            fields.append((match.group(1).strip(), _display_value(match.group(2))))
    if len(fields) < 2:
        return None

    lines = ["| Field | Value |", "| --- | --- |"]
    for label, value in fields:
        lines.append(f"| {label} | {value} |")
    return "\n".join(lines)


def try_deterministic_table_format(user_message: str, raw_data: str) -> Optional[str]:
    """Return a markdown table when *user_message* asks for one and *raw_data* is parseable."""
    if not wants_table_format(user_message):
        return None
    return _format_registered_clients_table(raw_data) or _format_profile_fields_table(raw_data)


def _phone_digit_count(token: str) -> int:
    return sum(ch.isdigit() for ch in token)


def _extract_phones(text: str) -> set[str]:
    """Return phone-like tokens with 7–15 digits (regional formats supported)."""
    # Blank out ISO dates (same length) so they don't register as phone numbers.
    text = _DATE_RE.sub(lambda m: " " * len(m.group(0)), text)
    phones: set[str] = set()
    occupied: list[tuple[int, int]] = []

    for pattern in (_PHONE_FORMATTED_RE, _PHONE_BARE_RE):
        for match in pattern.finditer(text):
            start, end = match.span()
            if any(start >= span_start and end <= span_end for span_start, span_end in occupied):
                continue
            token = match.group(0).strip()
            if 7 <= _phone_digit_count(token) <= 15:
                phones.add(token)
                occupied.append((start, end))
    return phones


def _client_name_from_profile(raw_data: str) -> str:
    for line in raw_data.splitlines():
        match = _PROFILE_FIELD_LINE.match(line.strip())
        if match and match.group(1).strip().lower() == "name":
            value = match.group(2).strip()
            if value not in ("(not set)", "(none)", "none"):
                return value
    return "The client"


def _format_single_profile_field(raw_data: str, hint: str) -> Optional[str]:
    """Return one sentence for a router hint like ``profile:email``."""
    label = _PROFILE_HINT_LABELS.get(hint)
    if not label:
        return None

    client_name = _client_name_from_profile(raw_data)
    field_key = hint.split(":", 1)[1]

    for line in raw_data.splitlines():
        match = _PROFILE_FIELD_LINE.match(line.strip())
        if match and match.group(1).strip().lower() == label.lower():
            value = match.group(2).strip()
            if value in ("(not set)", "(none)", "none"):
                return f"{client_name}'s {field_key} is not recorded yet."
            if field_key == "age":
                digits = value.rstrip(" years old").strip()
                return f"{client_name} is {digits} years old."
            return f"{client_name}'s {field_key} is {value}."
    return None


def _format_client_notes_numbered(raw_data: str) -> Optional[str]:
    """Parse ``list_client_notes`` tool output into a numbered list."""
    if raw_data.startswith("No notes"):
        return raw_data

    lines = raw_data.splitlines()
    entries: list[str] = []
    index = 0
    while index < len(lines):
        header_match = _NOTE_HEADER_LINE.match(lines[index].strip())
        if header_match is None:
            index += 1
            continue
        note_type = header_match.group("note_type")
        title = (header_match.group("title") or "").strip()
        date = header_match.group("date").strip()
        content = ""
        if index + 1 < len(lines):
            next_line = lines[index + 1]
            if next_line.startswith("  "):
                content = next_line.strip()
                index += 1
        header = f"[{note_type}]"
        if title:
            header += f" {title}"
        entry = f"{header} ({date})"
        if content:
            entry += f": {content}"
        entries.append(entry)
        index += 1

    if not entries:
        return None

    return "\n".join(f"{number}. {entry}" for number, entry in enumerate(entries, start=1))


def _format_compact_client_list(raw_data: str) -> Optional[str]:
    """Return a short sentence listing client names from ``list_clients`` output."""
    if "Registered clients:" not in raw_data:
        return None

    names = [match.group("name").strip() for match in _LIST_CLIENT_LINE.finditer(raw_data)]
    if not names:
        return None
    if len(names) == 1:
        return f"You have one client: {names[0]}."
    if len(names) == 2:
        return f"You have two clients: {names[0]} and {names[1]}."
    joined = ", ".join(names[:-1])
    return f"You have {len(names)} clients: {joined}, and {names[-1]}."


def try_deterministic_tool_format(
    user_message: str,
    raw_data: str,
    *,
    tool: str | None = None,
    hint: str | None = None,
) -> Optional[str]:
    """Return a tool-specific deterministic format when structure is known."""
    if tool == "list_client_notes":
        return _format_client_notes_numbered(raw_data)

    if tool == "list_clients" and not wants_table_format(user_message):
        return _format_compact_client_list(raw_data)

    if tool in ("get_client", "get_client_full") and hint:
        single = _format_single_profile_field(raw_data, hint)
        if single is not None:
            return single

    return None


def _formatter_system_prompt(tool: str | None = None) -> str:
    extra = _FORMATTER_TOOL_HINTS.get(tool or "", "")
    if not extra:
        return _FORMATTER_SYSTEM_PROMPT
    return f"{_FORMATTER_SYSTEM_PROMPT}\n\nTool-specific guidance:\n- {extra}"


def _extract_pii(text: str) -> set[str]:
    """Return all email addresses and phone numbers found in *text*."""
    emails = set(_EMAIL_RE.findall(text))
    return emails | _extract_phones(text)


def _pii_preserved(source: str, formatted: str) -> bool:
    """Return True when every PII token in *formatted* was present in *source*.

    This prevents the LLM from **inventing** contact details while still
    allowing focused answers (e.g. "Ali's email is …" when the question was
    only about email — the phone number from source need not appear).
    """
    for token in _extract_pii(formatted):
        if token not in source:
            log_step(logger, "formatter.pii", "hallucination",
                     level=logging.WARNING, token=token)
            return False
    return True


async def format_data_reply(
    user_message: str,
    reply: str,
    provider,
    *,
    tool: str | None = None,
    hint: str | None = None,
) -> str:
    """Return a human-friendly rephrasing of the fast-path *reply*.

    *reply* is the full string produced by :func:`~app.core.llm.try_direct_reply`
    (i.e. it starts with the deterministic template prefix).  The raw data
    section is extracted, sent to the LLM with a focused formatting prompt, and
    the result is validated before being returned.

    Falls back to the original *reply* on any error or PII validation failure so
    the coach always receives accurate data.

    Args:
        user_message: The original coach message (used to focus the rephrasing).
        reply: The deterministic template reply to be rephrased.
        provider: An :class:`~app.core.llm_providers.types.LLMProvider` instance.
        tool: Optional tool name from the fast path (e.g. ``list_client_notes``).
        hint: Optional router hint (e.g. ``profile:email``).

    Returns:
        A human-friendly string, or *reply* unchanged when formatting fails.
    """
    # The data-reply prefix gate also excludes write previews/outcomes/errors:
    # those are surfaced verbatim by the caller and never carry the prefix.
    if not reply or not reply.startswith(_DATA_REPLY_PREFIX):
        log_step(logger, "formatter", "skip", level=logging.DEBUG,
                 reason="no_data_prefix")
        return reply

    raw_data = reply.removeprefix(_DATA_REPLY_PREFIX)

    table = try_deterministic_table_format(user_message, raw_data)
    if table is not None:
        log_step(logger, "formatter", "ok", chars=len(table), mode="table")
        return table

    tool_format = try_deterministic_tool_format(
        user_message, raw_data, tool=tool, hint=hint
    )
    if tool_format is not None:
        log_step(logger, "formatter", "ok", chars=len(tool_format), mode="tool_hint")
        return tool_format

    if not settings.response_formatter_enabled:
        log_step(logger, "formatter", "skip", level=logging.DEBUG,
                 reason="disabled")
        return reply

    log_step(logger, "formatter", "start", level=logging.DEBUG,
             raw_chars=len(raw_data))

    try:
        messages = [
            {"role": "system", "content": _formatter_system_prompt(tool)},
            {
                "role": "user",
                "content": (
                    f"Coach's question: {user_message}\n\n"
                    f"Raw data from the database:\n{raw_data}"
                ),
            },
        ]
        result = await provider.complete(
            messages,
            temperature=settings.temperature_grounded,
            num_predict=settings.max_tokens_formatter,
        )
        formatted = result.content.strip()

        if not formatted:
            log_step(logger, "formatter", "fallback", level=logging.WARNING,
                     reason="llm_empty_reply")
            table = try_deterministic_table_format(user_message, raw_data)
            return table if table is not None else reply

        if not _pii_preserved(raw_data, formatted):
            log_step(logger, "formatter", "fallback", level=logging.WARNING,
                     reason="hallucinated_pii")
            table = try_deterministic_table_format(user_message, raw_data)
            return table if table is not None else reply

        log_step(logger, "formatter", "ok", chars=len(formatted))
        return formatted

    except Exception:
        logger.exception("response_formatter: LLM call failed, using template")
        log_step(logger, "formatter", "fallback", level=logging.WARNING,
                 reason="llm_exception")
        table = try_deterministic_table_format(user_message, raw_data)
        return table if table is not None else reply
