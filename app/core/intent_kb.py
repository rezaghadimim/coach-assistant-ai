"""Offline intent knowledge base for client-management commands.

Classifies a coach message into a client intent using a bank of example
phrasings matched with the same token-similarity math as the RAG retriever
(:mod:`app.rag.retriever`). This keeps the system fully offline with no new
dependencies, and the classifier interface is intentionally small so the
token-similarity backend could later be swapped for embeddings without
touching callers.

Only used as a *fallback* after deterministic regex matching: it returns a
match only when it is confident (score above a threshold and a clear margin
over the runner-up intent), otherwise ``None`` so callers defer to the LLM.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from app.rag.retriever import _tf_cosine as _cosine_similarity, _tokenize

# Default confidence thresholds. Tuned conservatively so pure coaching talk
# ("How can I support Ali emotionally?", "What should Ali focus on for his
# goals?") falls through to the LLM rather than being misclassified as a
# retrieval command. Can be overridden per-call for tuning.
DEFAULT_THRESHOLD = 0.45
DEFAULT_MARGIN = 0.08


@dataclass(frozen=True)
class _IntentSpec:
    """A logical intent and the tool/parameters it maps to."""

    key: str
    tool: str
    requires_client: bool
    examples: tuple[str, ...]
    note_type: Optional[str] = None
    # Precomputed token-frequency vectors for each example phrasing.
    _vectors: list[tuple[Counter[str], float]] = field(
        default_factory=list, compare=False, repr=False
    )

    def index(self) -> None:
        self._vectors.clear()
        for example in self.examples:
            tokens = _tokenize(example)
            if not tokens:
                continue
            tf = Counter(tokens)
            norm = math.sqrt(sum(value * value for value in tf.values()))
            self._vectors.append((tf, norm))

    def best_score(self, query_tf: Counter[str], query_norm: float) -> float:
        best = 0.0
        for tf, norm in self._vectors:
            score = _cosine_similarity(query_tf, query_norm, tf, norm)
            if score > best:
                best = score
        return best


@dataclass(frozen=True)
class IntentMatch:
    """Result of a confident classification."""

    intent: str
    tool: str
    requires_client: bool
    score: float
    note_type: Optional[str] = None


_INTENTS: tuple[_IntentSpec, ...] = (
    _IntentSpec(
        key="list_clients",
        tool="list_clients",
        requires_client=False,
        examples=(
            "who are my clients",
            "list my clients",
            "list all clients",
            "show me my clients",
            "show all my patients",
            "who are my patients",
            "list my patients",
            "which clients do i have",
            "show everyone i am coaching",
        ),
    ),
    _IntentSpec(
        key="get_client_full",
        tool="get_client_full",
        requires_client=True,
        examples=(
            "show me everything about the client",
            "get all data about the client",
            "give me the full details for the client",
            "show the complete record for this patient",
            "everything on file for the client",
            "full profile and notes for the client",
            "tell me all about the client",
            "get me the client's full details",
        ),
    ),
    _IntentSpec(
        key="get_client",
        tool="get_client",
        requires_client=True,
        examples=(
            "what is the client's email",
            "what is the client's phone number",
            "show me the client's contact details",
            "show the client's profile",
            "what is the patient's phone",
            "what is the client's contact information",
            "what is the client's age",
            "what is the client's occupation",
        ),
    ),
    _IntentSpec(
        key="list_notes",
        tool="list_client_notes",
        requires_client=True,
        examples=(
            "list all notes for the client",
            "show me the client's notes",
            "what notes do we have for the patient",
            "show all documentation for the client",
            "what have we written about the client",
            "show the notes on file for the client",
        ),
    ),
    _IntentSpec(
        key="list_notes_goal",
        tool="list_client_notes",
        requires_client=True,
        note_type="goal",
        examples=(
            "what are the client's goals",
            "show me the client's goals",
            "list the client's goals",
            "what goals does the client have",
            "what is the client working toward",
            "what are the patient's objectives",
            "show me their objectives",
            "list the client's objectives",
            "what objectives does the client have",
            "what are their current goals and objectives",
        ),
    ),
    _IntentSpec(
        key="list_notes_decision",
        tool="list_client_notes",
        requires_client=True,
        note_type="decision",
        examples=(
            "what decisions has the client made",
            "show me the client's decisions",
            "list the client's decisions",
            "what did the client decide",
            "show the decisions for this patient",
        ),
    ),
    _IntentSpec(
        key="list_notes_progress",
        tool="list_client_notes",
        requires_client=True,
        note_type="progress",
        examples=(
            "what progress has the client made",
            "show me the client's progress",
            "how is the client progressing",
            "list the client's progress updates",
            "what progress updates do we have for the client",
        ),
    ),
    _IntentSpec(
        key="list_notes_story",
        tool="list_client_notes",
        requires_client=True,
        note_type="story",
        examples=(
            "what is the client's story",
            "show me the client's background story",
            "tell me the client's background",
            "list the client's stories",
            "what background do we have on the client",
        ),
    ),
)


for _spec in _INTENTS:
    _spec.index()


def classify(
    message: str,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    margin: float = DEFAULT_MARGIN,
) -> Optional[IntentMatch]:
    """Classify a message into a client intent, or ``None`` if not confident.

    Returns a match only when the best intent's score is at least ``threshold``
    and exceeds the next-best *distinct* intent by at least ``margin``.
    """
    tokens = _tokenize(message)
    if not tokens:
        return None

    query_tf = Counter(tokens)
    query_norm = math.sqrt(sum(value * value for value in query_tf.values()))
    if query_norm == 0.0:
        return None

    scored = sorted(
        ((spec, spec.best_score(query_tf, query_norm)) for spec in _INTENTS),
        key=lambda item: item[1],
        reverse=True,
    )

    best_spec, best_score = scored[0]
    if best_score < threshold:
        return None

    runner_up_score = scored[1][1] if len(scored) > 1 else 0.0
    if best_score - runner_up_score < margin:
        return None

    return IntentMatch(
        intent=best_spec.key,
        tool=best_spec.tool,
        requires_client=best_spec.requires_client,
        score=best_score,
        note_type=best_spec.note_type,
    )
