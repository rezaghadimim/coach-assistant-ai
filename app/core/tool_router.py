"""Tool router — classifies a user message into the best-matching tool.

Two backends share the same :class:`ToolMatch` interface:

* **TokenBackend** — token-frequency cosine similarity over ``routing.jsonl``
  utterances; zero additional dependencies; used in CI and as fallback.
* **EmbeddingBackend** — dense cosine similarity over Ollama-generated vectors;
  requires ``karuniaperjuangan/multilingual-e5-small`` (or any embed model) to
  be running; more accurate for paraphrases and multilingual input.

Backend selection is controlled by ``settings.tool_router_backend``:
  * ``"token"``     — always use token backend
  * ``"embedding"`` — always use embedding backend (errors if Ollama unavailable)
  * ``"auto"``      — probe the embed model at first use; fall back to token if
                      the probe fails

The public API is intentionally small so the backend can be swapped or
extended without touching callers:

    match = classify_tool("Ali's age is 23")
    # → ToolMatch(tool="create_client", score=0.82, hint="profile:age", ...)

    count = build_index()   # (re)build index from routing.jsonl; returns example count
    reset_index()           # clear index (used by tests)
"""

from __future__ import annotations

import json
import logging
import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.rag.retriever import _tf_cosine as _cosine_similarity, _tokenize

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolMatch:
    """Confident tool classification result."""

    tool: str
    score: float
    hint: Optional[str] = None      # e.g. "note_type:goal", "profile:age"
    utterance: Optional[str] = None  # best-matching example (for debug/logs)
    backend: str = "token"


# ---------------------------------------------------------------------------
# Indexed example (shared by both backends)
# ---------------------------------------------------------------------------


@dataclass
class _Example:
    utterance: str
    tool: str
    hint: Optional[str]
    # Token backend fields (populated by TokenBackend.add)
    tf: Counter = field(default_factory=Counter)
    norm: float = 0.0
    # Embedding backend fields (populated by EmbeddingBackend.add)
    vector: list[float] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Token backend
# ---------------------------------------------------------------------------


class _TokenBackend:
    """In-memory token-frequency cosine similarity, same math as intent_kb."""

    def __init__(self) -> None:
        self._examples: list[_Example] = []

    def add(self, ex: _Example) -> None:
        tokens = _tokenize(ex.utterance)
        if not tokens:
            return
        tf = Counter(tokens)
        norm = math.sqrt(sum(v * v for v in tf.values()))
        ex.tf = tf
        ex.norm = norm
        self._examples.append(ex)

    def classify(
        self,
        message: str,
        *,
        threshold: float,
        margin: float,
    ) -> Optional[ToolMatch]:
        tokens = _tokenize(message)
        if not tokens or not self._examples:
            return None

        query_tf = Counter(tokens)
        query_norm = math.sqrt(sum(v * v for v in query_tf.values()))
        if query_norm == 0.0:
            return None

        scored = sorted(
            (
                (ex, _cosine_similarity(query_tf, query_norm, ex.tf, ex.norm))
                for ex in self._examples
                if ex.norm > 0.0
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        if not scored:
            return None

        best_ex, best_score = scored[0]
        if best_score < threshold:
            return None

        # Find best score for a *different* tool (runner-up across tools)
        runner_up = 0.0
        for ex, score in scored[1:]:
            if ex.tool != best_ex.tool:
                runner_up = score
                break

        if best_score - runner_up < margin:
            return None

        return ToolMatch(
            tool=best_ex.tool,
            score=best_score,
            hint=best_ex.hint,
            utterance=best_ex.utterance,
            backend="token",
        )

    def __len__(self) -> int:
        return len(self._examples)

    def clear(self) -> None:
        self._examples.clear()


# ---------------------------------------------------------------------------
# Embedding backend
# ---------------------------------------------------------------------------


class _EmbeddingBackend:
    """Dense cosine similarity over Ollama-generated vectors."""

    def __init__(self) -> None:
        self._examples: list[_Example] = []

    def add(self, ex: _Example) -> None:
        # Vectors are pre-computed by build_index; just store.
        self._examples.append(ex)

    def classify(
        self,
        message: str,
        *,
        threshold: float,
        margin: float,
    ) -> Optional[ToolMatch]:
        if not self._examples:
            return None

        from app.core.embeddings import cosine_similarity, embed_query

        try:
            query_vec = embed_query(message)
        except Exception as exc:
            logger.warning("embedding classify failed: %s", exc)
            return None

        scored = sorted(
            (
                (ex, cosine_similarity(query_vec, ex.vector))
                for ex in self._examples
                if ex.vector
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        if not scored:
            return None

        best_ex, best_score = scored[0]
        if best_score < threshold:
            return None

        runner_up = 0.0
        for ex, score in scored[1:]:
            if ex.tool != best_ex.tool:
                runner_up = score
                break

        if best_score - runner_up < margin:
            return None

        return ToolMatch(
            tool=best_ex.tool,
            score=best_score,
            hint=best_ex.hint,
            utterance=best_ex.utterance,
            backend="embedding",
        )

    def __len__(self) -> int:
        return len(self._examples)

    def clear(self) -> None:
        self._examples.clear()


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_token_backend = _TokenBackend()
_embed_backend = _EmbeddingBackend()
_index_built = False
# Cached result of the embed-model probe for "auto" backend
_embed_available: Optional[bool] = None


def _routing_jsonl_path() -> Path:
    return Path(settings.tool_knowledge_dir) / "examples" / "routing.jsonl"


def _load_examples() -> list[_Example]:
    path = _routing_jsonl_path()
    if not path.exists():
        logger.warning("tool router: routing.jsonl not found at %s", path)
        return []
    examples: list[_Example] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            utterance = row.get("utterance", "").strip()
            tool = row.get("tool", "").strip()
            hint = row.get("hint")
            if utterance and tool:
                examples.append(_Example(utterance=utterance, tool=tool, hint=hint))
    return examples


def build_index(*, force: bool = False) -> int:
    """Load ``routing.jsonl``, build token and/or embedding index, return example count.

    Idempotent — skips rebuild unless ``force=True``. Called automatically on
    the first :func:`classify_tool` call and via ``POST /api/tools/reindex``.
    """
    global _index_built, _embed_available

    if _index_built and not force:
        return len(_token_backend)

    _token_backend.clear()
    _embed_backend.clear()

    examples = _load_examples()
    if not examples:
        _index_built = True
        return 0

    # Always build the token index (free, no network).
    for ex in examples:
        _token_backend.add(ex)

    # Build embedding index when backend is "embedding" or "auto".
    backend_setting = settings.tool_router_backend.lower()
    if backend_setting in ("embedding", "auto"):
        if _embed_available is None:
            from app.core.embeddings import probe_embed_model
            _embed_available = probe_embed_model()
            if _embed_available:
                logger.info(
                    "tool router: embed model '%s' available — building embedding index",
                    settings.ollama_embed_model,
                )
            else:
                logger.info(
                    "tool router: embed model unavailable — falling back to token backend"
                )

        if _embed_available:
            from app.core.embeddings import embed_texts
            try:
                utterances = [ex.utterance for ex in examples]
                vectors = embed_texts(utterances, input_type="passage")
                for ex, vec in zip(examples, vectors):
                    ex.vector = vec
                    _embed_backend.add(ex)
                logger.info(
                    "tool router: embedding index built (%d examples)", len(_embed_backend)
                )
            except Exception as exc:
                logger.warning("tool router: embedding index build failed: %s", exc)
                _embed_available = False

    _index_built = True
    logger.info("tool router: token index built (%d examples)", len(_token_backend))
    return len(_token_backend)


def reset_index() -> None:
    """Clear all indexes (used by tests)."""
    global _index_built, _embed_available
    _token_backend.clear()
    _embed_backend.clear()
    _index_built = False
    _embed_available = None


def classify_tool(
    message: str,
    *,
    threshold: Optional[float] = None,
    margin: Optional[float] = None,
) -> Optional[ToolMatch]:
    """Classify a message into the best-matching tool, or ``None`` if not confident.

    Uses the configured backend (embedding → token → None). Index is built
    lazily on the first call.

    Args:
        message: Raw user message.
        threshold: Override ``settings.tool_router_threshold``.
        margin: Override ``settings.tool_router_margin``.

    Returns:
        :class:`ToolMatch` when confident, ``None`` to defer to LLM.
    """
    if not settings.tool_router_enabled:
        return None

    if not _index_built:
        build_index()

    t = threshold if threshold is not None else settings.tool_router_threshold
    m = margin if margin is not None else settings.tool_router_margin

    backend_setting = settings.tool_router_backend.lower()

    # Embedding path
    use_embed = (
        backend_setting == "embedding"
        or (backend_setting == "auto" and _embed_available)
    )
    if use_embed and len(_embed_backend) > 0:
        result = _embed_backend.classify(message, threshold=t, margin=m)
        if result is not None:
            return result
        # Fall through to token on low confidence (not on error — error is logged)

    # Token path
    return _token_backend.classify(message, threshold=t, margin=m)


def top_n_tools(
    message: str,
    n: int = 3,
    *,
    threshold: float = 0.0,
) -> list[ToolMatch]:
    """Return top-N tool candidates sorted by score (no margin filtering).

    Useful for debug API and eval scripts. Always uses the token backend for
    predictability.
    """
    if not _index_built:
        build_index()

    tokens = _tokenize(message)
    if not tokens or not _token_backend._examples:
        return []

    query_tf = Counter(tokens)
    query_norm = math.sqrt(sum(v * v for v in query_tf.values()))
    if query_norm == 0.0:
        return []

    scored = sorted(
        (
            (ex, _cosine_similarity(query_tf, query_norm, ex.tf, ex.norm))
            for ex in _token_backend._examples
            if ex.norm > 0.0
        ),
        key=lambda item: item[1],
        reverse=True,
    )

    seen: set[str] = set()
    results: list[ToolMatch] = []
    for ex, score in scored:
        if score < threshold:
            break
        if ex.tool not in seen:
            seen.add(ex.tool)
            results.append(
                ToolMatch(
                    tool=ex.tool,
                    score=score,
                    hint=ex.hint,
                    utterance=ex.utterance,
                    backend="token",
                )
            )
        if len(results) >= n:
            break
    return results
