"""Coaching-only scope guardrail.

Deterministic backstop that keeps the assistant focused on coaching,
personal growth, wellbeing, and client-management topics. Clearly off-topic
requests are declined with a fixed redirect, while Open WebUI's auto-generated
task prompts (follow-up suggestions, title, tags) are always allowed through.
"""

from __future__ import annotations

import re
from typing import Optional

OFF_TOPIC_REFUSAL = (
    "I'm your coaching assistant, so I keep our work focused on coaching, "
    "personal growth, wellbeing, and your clients. I can't help with that "
    "request, but I'd love to. What's something you'd like to work on for "
    "yourself or one of your clients today?"
)

# Markers that identify Open WebUI's hidden task prompts (follow-up
# suggestions, chat title, and tag generation). These are system-generated and
# must never be treated as off-topic user questions.
_OPENWEBUI_TASK_MARKERS = (
    "### task:",
    "### output:",
    "### chat history:",
    "{{messages",
    '"follow_ups"',
    '"title"',
    '"tags"',
)

# Conservative denylist of clearly non-coaching requests. Tuned to avoid
# false positives on coaching language (goals, stress, career, habits, etc.).
_OFF_TOPIC_PATTERNS = (
    # Programming / code
    re.compile(r"\b(write|debug|fix|refactor|compile|optimize)\b.{0,40}\bcode\b", re.IGNORECASE),
    re.compile(r"\b(python|javascript|java|c\+\+|sql|html|css|regex|function|algorithm)\b", re.IGNORECASE),
    # Math / calculations
    re.compile(r"\b(calculate|compute|solve)\b.{0,30}\b(equation|integral|derivative|sum|product)\b", re.IGNORECASE),
    re.compile(r"what\s+is\s+\d+\s*[\+\-\*/x]\s*\d+", re.IGNORECASE),
    # Weather
    re.compile(r"\b(weather|forecast|temperature)\b.{0,30}\b(today|tomorrow|outside|in)\b", re.IGNORECASE),
    # Sports scores
    re.compile(r"\b(who\s+won|score|final\s+score|game\s+last\s+night)\b", re.IGNORECASE),
    # Trivia / general knowledge
    re.compile(r"\b(capital\s+of|population\s+of|how\s+tall|how\s+far|distance\s+(from|to|between))\b", re.IGNORECASE),
    # Translation
    re.compile(r"\btranslate\b.{0,30}\b(to|into|from)\b", re.IGNORECASE),
    # Recipes / cooking
    re.compile(r"\b(recipe|how\s+to\s+cook|how\s+to\s+bake|ingredients\s+for)\b", re.IGNORECASE),
    # Current news / events
    re.compile(r"\b(latest\s+news|breaking\s+news|stock\s+price|who\s+is\s+the\s+president)\b", re.IGNORECASE),
)


def is_openwebui_task(message: str) -> bool:
    """Return True when the message is an Open WebUI auto-generated task prompt."""
    lowered = message.lower()
    return any(marker in lowered for marker in _OPENWEBUI_TASK_MARKERS)


def is_off_topic(message: str) -> bool:
    """Return True for messages that are clearly outside the coaching scope."""
    text = message.strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _OFF_TOPIC_PATTERNS)


def scope_guard(message: str) -> Optional[str]:
    """Return a fixed refusal for off-topic messages, else None.

    Open WebUI task prompts are always allowed through (return None) so that
    follow-up suggestions, titles, and tags keep working.
    """
    if is_openwebui_task(message):
        return None
    if is_off_topic(message):
        return OFF_TOPIC_REFUSAL
    return None
