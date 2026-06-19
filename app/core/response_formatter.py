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
- Gated by ``settings.response_formatter_enabled`` (default ``False``).
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
# Phone numbers: at least 7 digits optionally separated by spaces, dashes,
# parentheses, dots, or a leading +.
_PHONE_RE = re.compile(r"\+?[\d][\d\s\-\(\)\.]{5,}\d")

_TABLE_INTENT = re.compile(
    r"\b(?:table|tabular|spreadsheet|grid|matrix|columns?)\b",
    re.IGNORECASE,
)
_LIST_CLIENT_LINE = re.compile(
    r"^\s*-?\s*(?P<name>.+?)\s+\(ID:\s*(?P<id>[^,)]+),\s*Email:\s*(?P<email>.+?)\)\s*$",
    re.MULTILINE,
)
_PROFILE_FIELD_LINE = re.compile(r"^([A-Za-z][A-Za-z ]*): (.+)$", re.MULTILINE)

_FORMATTER_SYSTEM_PROMPT = """\
You are a data presentation assistant for a life-coaching app.
Your only job is to rephrase raw client database output as a short, natural reply to the coach's question.

Rules (STRICT):
- Answer ONLY what the coach asked. If they asked for an email, return just the email in a short sentence.
- If the coach asked for a specific field (e.g. email, phone, age), return ONLY that field — do not dump the whole profile.
- If the coach asked for a table or multi-column format, produce a clean markdown table with only the columns they requested.
- Use warm, conversational language where appropriate; use a table when the coach asked for one.
- NEVER invent, omit, or paraphrase any contact details (email addresses, phone numbers, client IDs).
- NEVER add follow-up questions, coaching suggestions, or unsolicited advice.
- NEVER produce JSON, XML, or markdown code blocks.
- If a field value is "(not set)", show it as empty in the table or say it is not recorded yet.
- Keep the reply short: one to three sentences for profile lookups; a compact table for multi-client results.
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


def _extract_pii(text: str) -> set[str]:
    """Return all email addresses and phone numbers found in *text*."""
    emails = set(_EMAIL_RE.findall(text))
    phones = {m.strip() for m in _PHONE_RE.findall(text)}
    return emails | phones


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

    Returns:
        A human-friendly string, or *reply* unchanged when formatting fails.
    """
    if not reply or reply.startswith(("❌", "⏳", "✅")):
        log_step(logger, "formatter", "skip", level=logging.DEBUG,
                 reason="write_error_or_empty")
        return reply

    if not reply.startswith(_DATA_REPLY_PREFIX):
        log_step(logger, "formatter", "skip", level=logging.DEBUG,
                 reason="no_data_prefix")
        return reply

    raw_data = reply.removeprefix(_DATA_REPLY_PREFIX)

    table = try_deterministic_table_format(user_message, raw_data)
    if table is not None:
        log_step(logger, "formatter", "ok", chars=len(table), mode="table")
        return table

    if not settings.response_formatter_enabled:
        log_step(logger, "formatter", "skip", level=logging.DEBUG,
                 reason="disabled")
        return reply

    log_step(logger, "formatter", "start", level=logging.DEBUG,
             raw_chars=len(raw_data))

    try:
        messages = [
            {"role": "system", "content": _FORMATTER_SYSTEM_PROMPT},
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
