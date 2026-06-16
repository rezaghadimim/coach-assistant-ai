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

from app.core.config import settings

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
            logger.warning(
                "response_formatter: hallucinated PII token in output: %r", token
            )
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
        logger.info(
            "response_formatter: SKIP (write/error/empty reply) — returning as-is"
        )
        return reply

    if not reply.startswith(_DATA_REPLY_PREFIX):
        # Not a fast-path data reply — return unchanged without an LLM call.
        logger.info(
            "response_formatter: SKIP (no data prefix) — not a formattable reply"
        )
        return reply

    raw_data = reply.removeprefix(_DATA_REPLY_PREFIX)
    logger.info(
        "response_formatter: FORMATTING question=%r (%d chars of raw data)",
        user_message,
        len(raw_data),
    )

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
            num_predict=settings.max_tokens_classify,
        )
        formatted = result.content.strip()

        if not formatted:
            logger.warning(
                "response_formatter: FALLBACK — LLM returned empty reply, using template"
            )
            return reply

        if not _pii_preserved(raw_data, formatted):
            logger.warning(
                "response_formatter: FALLBACK — hallucinated PII detected, using template "
                "(output=%r)",
                formatted,
            )
            return reply

        logger.info("response_formatter: SUCCESS — returning formatted reply")
        return formatted

    except Exception:
        logger.exception(
            "response_formatter: FALLBACK — LLM call failed, using deterministic template"
        )
        return reply
