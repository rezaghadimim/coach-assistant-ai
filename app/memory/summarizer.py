"""Session summarization helpers.

Uses the LLM (via SUMMARIZER_PROMPT) to produce a structured coaching session
record. Falls back to a fast heuristic when the LLM is unavailable so session
rollover never blocks.
"""

from __future__ import annotations

import logging

from app.core.llm_providers.ollama import OllamaProvider
from app.core.observability import log_step

logger = logging.getLogger(__name__)


def _heuristic_summary(messages: list[dict[str, str]]) -> str:
    """Fast, offline fallback summary built from message content."""
    user_messages = [
        m["content"].strip()
        for m in messages
        if m["role"] == "user" and m["content"].strip()
    ]
    assistant_messages = [
        m["content"].strip()
        for m in messages
        if m["role"] == "assistant" and m["content"].strip()
    ]

    discussed_topics = "; ".join(user_messages[:5]) if user_messages else "No client topics captured."
    coach_focus = assistant_messages[-1] if assistant_messages else "No coach guidance yet."
    total_exchanges = min(len(user_messages), len(assistant_messages))

    return (
        "## Coaching Session Record\n"
        f"- **Topics Discussed**: {discussed_topics}\n"
        f"- **Total Exchanges**: {total_exchanges}\n"
        f"- **Latest Coach Focus**: {coach_focus}\n"
        f"- **Messages from Client**: {len(user_messages)}\n"
        f"- **Coach Responses**: {len(assistant_messages)}"
    )


async def summarize_session(messages: list[dict[str, str]]) -> str:
    """Generate a structured coaching session summary using the LLM.

    Falls back to heuristic summarization when the LLM is unreachable or
    returns an empty response.
    """
    if not messages:
        return _heuristic_summary(messages)

    from app.core.prompts import SUMMARIZER_PROMPT

    conversation_text = "\n".join(
        f"{m['role'].upper()}: {m['content']}"
        for m in messages
        if m.get("content", "").strip()
    )

    llm_messages = [
        {"role": "user", "content": f"{SUMMARIZER_PROMPT}\n\n{conversation_text}"},
    ]

    try:
        provider = OllamaProvider()
        result = await provider.complete(llm_messages)
        summary = result.content.strip()
        if summary:
            log_step(logger, "summary", "ok", chars=len(summary))
            return summary
        log_step(logger, "summary", "fallback", level=logging.WARNING,
                 reason="llm_empty_reply")
    except Exception as exc:
        log_step(logger, "summary", "fallback", level=logging.WARNING,
                 reason="llm_exception", exc=type(exc).__name__)

    return _heuristic_summary(messages)
