"""Domain synonym lexicon for tool-routing normalization.

Expands out-of-vocabulary user terms to canonical coaching-domain terms so the
token and embedding backends can match phrasings like "give me all visitors in
table" to ``list_clients``.

Strategy — additive query expansion, not destructive replacement:
  "give me all visitors in table"
  → "give me all visitors in table client list clients"

This avoids corrupting proper names or ambiguous tokens while still injecting
canonical signal for similarity matching.

Apply only router-locally (never to the shared RAG tokenizer or embedding path).
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Synonym mapping: surface term → canonical expansion tokens
# ---------------------------------------------------------------------------
# Keys are lowercase strings (or regex fragments) that map to canonical tokens
# appended to the query.  Each canonical token should appear in ``routing.jsonl``
# examples so both the token and embedding backends can match.

_SYNONYMS: list[tuple[re.Pattern[str], list[str]]] = [
    # People/participant synonyms → "client"
    (
        re.compile(
            r"\b(?:visitor|visitors|person|people|contact|contacts|"
            r"individual|individuals|member|members|attendee|attendees|"
            r"coachee|coachees|participant|participants|patient|patients)\b",
            re.IGNORECASE,
        ),
        ["client", "clients"],
    ),
    # Collection/store synonyms → "clients list"
    (
        re.compile(
            r"\b(?:table|database|db|records|roster|everyone|everybody|"
            r"all of them|whole list|full list|all users)\b",
            re.IGNORECASE,
        ),
        ["clients", "list", "list clients"],
    ),
    # Retrieval verbs not in routing examples
    (
        re.compile(
            r"\b(?:dump|fetch|pull|grab|retrieve|display|print|output|export)\b",
            re.IGNORECASE,
        ),
        ["show", "get", "list"],
    ),
    # Note / memo synonyms
    (
        re.compile(
            r"\b(?:memo|memos|entry|entries|log entry|log entries|remark|remarks|"
            r"annotation|annotations|comment|comments)\b",
            re.IGNORECASE,
        ),
        ["note", "notes"],
    ),
    # Goal / objective synonyms
    (
        re.compile(
            r"\b(?:objective|objectives|aim|aims|target|targets|aspiration|aspirations|"
            r"milestone|milestones)\b",
            re.IGNORECASE,
        ),
        ["goal", "goals"],
    ),
    # Progress synonyms
    (
        re.compile(
            r"\b(?:advancement|improvement|development|update|updates|achievement|achievements)\b",
            re.IGNORECASE,
        ),
        ["progress"],
    ),
    # Story / background synonyms
    (
        re.compile(
            r"\b(?:history|background|backstory|narrative|biography|bio)\b",
            re.IGNORECASE,
        ),
        ["story", "background"],
    ),
    # Decision synonyms
    (
        re.compile(
            r"\b(?:choice|choices|resolution|resolutions|commitment|commitments|"
            r"conclusion|conclusions)\b",
            re.IGNORECASE,
        ),
        ["decision", "decisions"],
    ),
]


def normalize_for_routing(text: str) -> str:
    """Return *text* with canonical synonym tokens appended.

    Original text is preserved; matched synonyms are appended at the end so
    they add cosine weight without replacing any original tokens.

    Examples
    --------
    >>> normalize_for_routing("Give me all visitors in table")
    'Give me all visitors in table client clients clients list list clients'
    >>> normalize_for_routing("Who are my clients?")  # already canonical
    'Who are my clients?'
    """
    extras: list[str] = []
    seen: set[str] = set()

    for pattern, canonical_tokens in _SYNONYMS:
        if pattern.search(text):
            for token in canonical_tokens:
                if token not in seen:
                    seen.add(token)
                    extras.append(token)

    if not extras:
        return text
    return text + " " + " ".join(extras)
