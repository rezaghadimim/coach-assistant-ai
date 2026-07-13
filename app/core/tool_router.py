"""Tool router — classifies a user message into the best-matching tool.

Three backends share the same :class:`ToolMatch` interface:

* **TokenBackend** — token-frequency cosine similarity over ``routing.jsonl``
  utterances; zero additional dependencies; used in CI and as fallback.
* **EmbeddingBackend** — dense cosine similarity over Ollama-generated vectors;
  requires ``karuniaperjuangan/multilingual-e5-small`` (or any embed model) to
  be running; more accurate for paraphrases and multilingual input.
* **ReRankBackend** — two-stage: embedding top-K recall → fastembed cross-encoder
  precision; requires both Ollama embed model and ``fastembed`` to be installed;
  best accuracy for out-of-vocabulary/synonym phrasing.

All backends degrade gracefully:
  rerank → embedding → token → None (defer to LLM)

Backend selection is controlled by ``settings.tool_router_backend``:
  * ``"token"``     — always use token backend
  * ``"embedding"`` — always use embedding backend (errors if Ollama unavailable)
  * ``"auto"``      — probe the embed model at first use; fall back to token if
                      the probe fails; use rerank on top of embedding when
                      ``settings.tool_router_rerank_enabled`` is True and
                      fastembed is available

Domain synonym normalization (``app.core.lexicon.normalize_for_routing``) is
applied to the query string for both token and embedding stages so out-of-vocab
phrasings like "give me all visitors in table" match ``list_clients`` examples.

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
import threading
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.core.observability import log_step
from app.rag.retriever import tf_cosine as _cosine_similarity, tokenize

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolMatch:
    """Confident tool classification result."""

    tool: str
    score: float
    hint: Optional[str] = None       # e.g. "note_type:goal", "profile:age"
    utterance: Optional[str] = None  # best-matching example (for debug/logs)
    backend: str = "token"
    rerank_score: Optional[float] = None  # cross-encoder score when backend="rerank"


# ---------------------------------------------------------------------------
# Indexed example (shared by all backends)
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
        # Normalize symmetrically with classify(): queries get canonical synonym
        # tokens appended, so examples must too — otherwise the appended tokens
        # dilute the query norm and an exact utterance match scores well below
        # 1.0 (e.g. "Fetch all contacts" ≈ 0.61 against its own corpus entry).
        from app.core.lexicon import normalize_for_routing

        tokens = tokenize(normalize_for_routing(ex.utterance))
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
        from app.core.lexicon import normalize_for_routing

        normalized = normalize_for_routing(message)
        tokens = tokenize(normalized)
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

    def top_k(
        self,
        message: str,
        k: int,
        floor: float = 0.0,
    ) -> list[tuple[_Example, float]]:
        """Return up to *k* examples with cosine score >= *floor*, sorted descending."""
        if not self._examples:
            return []

        from app.core.embeddings import cosine_similarity, embed_query
        from app.core.lexicon import normalize_for_routing

        try:
            normalized = normalize_for_routing(message)
            query_vec = embed_query(normalized)
        except Exception as exc:
            logger.warning("embedding top_k failed: %s", exc)
            return []

        scored = sorted(
            (
                (ex, cosine_similarity(query_vec, ex.vector))
                for ex in self._examples
                if ex.vector
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        return [(ex, score) for ex, score in scored if score >= floor][:k]

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
        from app.core.lexicon import normalize_for_routing

        try:
            normalized = normalize_for_routing(message)
            query_vec = embed_query(normalized)
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
# Two-stage rerank helper
# ---------------------------------------------------------------------------


def _rerank_candidates(
    message: str,
    candidates: list[tuple[_Example, float]],
    *,
    threshold: float,
    margin: float,
    model: str,
) -> tuple[Optional[ToolMatch], list[ToolMatch]]:
    """Stage-2 cross-encoder rerank over *candidates* (from stage-1 embedding top-K).

    Calls ``rerank_documents`` from :mod:`app.core.rerank` over the candidate
    utterances, selects the highest-scoring example, applies threshold and
    cross-tool margin.

    Returns ``(match, ranked)`` where *match* is a confident :class:`ToolMatch`
    or ``None``, and *ranked* is the top tools by rerank score (reused for
    deferral observability so the caller need not recompute them).
    """
    from app.core.rerank import rerank_documents

    if not candidates:
        log_step(logger, "tool_router.rerank", "skip", level=logging.DEBUG,
                 reason="no_candidates")
        return None, []

    utterances = [ex.utterance for ex, _ in candidates]
    embed_scores = [score for _, score in candidates]

    log_step(logger, "tool_router.embed_recall", "ok", level=logging.DEBUG,
             candidates=len(candidates))

    try:
        rerank_scores = rerank_documents(message, utterances, model=model, batch_size=32)
    except Exception as exc:
        log_step(logger, "tool_router.rerank", "fail", level=logging.WARNING,
                 exc=type(exc).__name__)
        return None, []

    if len(rerank_scores) != len(candidates):
        log_step(logger, "tool_router.rerank", "fail", level=logging.WARNING,
                 reason="score_count_mismatch",
                 expected=len(candidates), got=len(rerank_scores))
        return None, []

    # Find best and runner-up across tools using rerank scores.
    scored = sorted(
        zip(rerank_scores, embed_scores, (ex for ex, _ in candidates)),
        key=lambda t: t[0],
        reverse=True,
    )
    ranked = _aggregate_tool_matches(
        [(ex, embed_s, rerank_s) for rerank_s, embed_s, ex in scored], "rerank", 3
    )

    best_rerank, best_embed, best_ex = scored[0]
    if best_rerank < threshold:
        log_step(logger, "tool_router.rerank", "miss", level=logging.DEBUG,
                 best_tool=best_ex.tool, score=best_rerank, threshold=threshold)
        return None, ranked

    # Runner-up: best score from a *different* tool.
    runner_up_rerank = 0.0
    for rerank_s, _embed_s, ex in scored[1:]:
        if ex.tool != best_ex.tool:
            runner_up_rerank = rerank_s
            break

    if best_rerank - runner_up_rerank < margin:
        log_step(logger, "tool_router.rerank", "miss", level=logging.DEBUG,
                 best_tool=best_ex.tool, score=best_rerank,
                 margin=best_rerank - runner_up_rerank, required_margin=margin)
        return None, ranked

    log_step(logger, "tool_router.rerank", "hit",
             tool=best_ex.tool, score=best_rerank,
             embed_score=best_embed, margin=best_rerank - runner_up_rerank)

    match = ToolMatch(
        tool=best_ex.tool,
        score=best_embed,
        hint=best_ex.hint,
        utterance=best_ex.utterance,
        backend="rerank",
        rerank_score=best_rerank,
    )
    return match, ranked


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_token_backend = _TokenBackend()
_embed_backend = _EmbeddingBackend()
_index_built = False
# Serializes the clear/populate/set-flag sequence in build_index so a
# concurrent classify_tool (or a second builder) can never observe a
# half-cleared/half-populated index once workers or a threadpool are used.
_build_lock = threading.Lock()
# Cached result of the embed-model probe for "auto" backend
_embed_available: Optional[bool] = None
# Cached result of the rerank-model probe
_rerank_available: Optional[bool] = None


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
    global _index_built, _embed_available, _rerank_available

    if _index_built and not force:
        return len(_token_backend)

    with _build_lock:
        # Re-check under the lock: another thread may have finished building
        # while we waited for it.
        if _index_built and not force:
            return len(_token_backend)
        return _build_index_locked()


def _build_index_locked() -> int:
    """Build the index. Caller must hold ``_build_lock``.

    Builds into fresh backend objects and swaps the module globals only after
    both are fully populated, so lock-free readers (classify_tool is on the
    hot path) always observe either the old or the new complete index — never
    a half-built one during a forced reindex.
    """
    global _token_backend, _embed_backend, _index_built
    global _embed_available, _rerank_available

    token_backend = _TokenBackend()
    embed_backend = _EmbeddingBackend()

    examples = _load_examples()
    if not examples:
        _token_backend = token_backend
        _embed_backend = embed_backend
        _index_built = True
        return 0

    # Always build the token index (free, no network).
    for ex in examples:
        token_backend.add(ex)

    # Build embedding index when backend is "embedding" or "auto".
    backend_setting = settings.tool_router_backend.lower()
    if backend_setting in ("embedding", "auto"):
        if _embed_available is None:
            from app.core.embeddings import probe_embed_model
            _embed_available = probe_embed_model()
            if _embed_available:
                logger.info(
                    "tool router: embed model '%s' available — building embedding index",
                    settings.rag_embed_model,
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
                    embed_backend.add(ex)
                logger.info(
                    "tool router: embedding index built (%d examples)", len(embed_backend)
                )
            except Exception as exc:
                logger.warning("tool router: embedding index build failed: %s", exc)
                _embed_available = False

        # Probe rerank model if reranking is enabled.
        if _embed_available and settings.tool_router_rerank_enabled:
            if _rerank_available is None:
                from app.core.rerank import probe_rerank_model
                _rerank_available = probe_rerank_model(
                    model=settings.tool_router_rerank_model
                )
                if _rerank_available:
                    logger.info(
                        "tool router: cross-encoder '%s' available — rerank stage enabled",
                        settings.tool_router_rerank_model,
                    )
                else:
                    logger.info(
                        "tool router: cross-encoder unavailable — rerank stage disabled"
                    )

    # Atomic swap: readers see the old index right up to this point.
    _token_backend = token_backend
    _embed_backend = embed_backend
    _index_built = True
    logger.info("tool router: token index built (%d examples)", len(token_backend))
    return len(token_backend)


def effective_backend() -> str:
    """Return the backend actually in use after index build + probes.

    Differs from ``settings.tool_router_backend`` when "auto" or "embedding" has
    silently degraded to token because the Ollama embed model (or the rerank
    cross-encoder) is unavailable. Callers use this to surface the degradation
    instead of reporting the configured value as if it were live.
    """
    configured = settings.tool_router_backend.lower()
    if configured == "token":
        return "token"
    # "embedding" / "auto": embedding only runs when the probe passed and the
    # index actually populated.
    if not (_embed_available and len(_embed_backend) > 0):
        return "token"
    if settings.tool_router_rerank_enabled and _rerank_available:
        return "rerank"
    return "embedding"


def is_degraded() -> bool:
    """True when the configured backend could not be honored (running below it)."""
    configured = settings.tool_router_backend.lower()
    if configured in ("token", "auto"):
        # "auto" degrading to token is expected fallback, but still worth flagging
        # so operators notice Ollama is down; "token" is never degraded.
        return configured == "auto" and effective_backend() == "token"
    # Explicit "embedding"/"rerank" request that fell back to token is a hard miss.
    return effective_backend() != _resolve_requested_backend(configured)


def _resolve_requested_backend(configured: str) -> str:
    """The best backend the configuration explicitly asked for."""
    if configured == "embedding":
        return "rerank" if settings.tool_router_rerank_enabled else "embedding"
    return configured


def reset_index() -> None:
    """Clear all indexes (used by tests)."""
    global _token_backend, _embed_backend
    global _index_built, _embed_available, _rerank_available
    _token_backend = _TokenBackend()
    _embed_backend = _EmbeddingBackend()
    _index_built = False
    _embed_available = None
    _rerank_available = None


def classify_tool(
    message: str,
    *,
    threshold: Optional[float] = None,
    margin: Optional[float] = None,
) -> Optional[ToolMatch]:
    """Classify a message into the best-matching tool, or ``None`` if not confident.

    Tries backends in this order, falling through on low confidence or error:
      1. Two-stage rerank (embed top-K → cross-encoder) when available
      2. Embedding-only cosine when available
      3. Token-frequency cosine (always available)
      4. None — defer to LLM

    Index is built lazily on the first call.

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

    use_embed = (
        backend_setting == "embedding"
        or (backend_setting == "auto" and _embed_available)
    )

    # Candidates seen during the attempt, reused for deferral observability so
    # the miss path never re-embeds or re-reranks the same query.
    deferral_candidates: list[ToolMatch] = []
    deferral_backend = "token"

    # --- Two-stage rerank path ---
    if (
        use_embed
        and len(_embed_backend) > 0
        and settings.tool_router_rerank_enabled
        and _rerank_available
    ):
        candidates = _embed_backend.top_k(
            message,
            k=settings.tool_router_rerank_top_k,
            floor=settings.tool_router_embed_floor,
        )
        if candidates:
            result, ranked = _rerank_candidates(
                message,
                candidates,
                threshold=settings.tool_router_rerank_threshold,
                margin=settings.tool_router_rerank_margin,
                model=settings.tool_router_rerank_model,
            )
            if result is not None:
                log_step(logger, "tool_router", "hit",
                         backend="rerank", tool=result.tool,
                         score=result.rerank_score or result.score)
                return result
            # Fall through to embedding-only on low confidence.
            if ranked:
                deferral_candidates = ranked
                deferral_backend = "rerank"
        else:
            log_step(logger, "tool_router.embed_recall", "miss", level=logging.DEBUG,
                     reason="below_floor")

    # --- Embedding-only path ---
    if use_embed and len(_embed_backend) > 0:
        result = _embed_backend.classify(message, threshold=t, margin=m)
        if result is not None:
            log_step(logger, "tool_router", "hit",
                     backend="embedding", tool=result.tool, score=result.score)
            return result
        log_step(logger, "tool_router.embed_fallback", "miss", level=logging.DEBUG)
        # Fall through to token on low confidence.

    # --- Token path ---
    result = _token_backend.classify(message, threshold=t, margin=m)
    if result is not None:
        log_step(logger, "tool_router", "hit",
                 backend="token", tool=result.tool, score=result.score)
        return result

    # All backends deferred. Reuse the rerank candidates if we already have them;
    # otherwise build a cheap top-N (embedding-only / token setups, or below-floor).
    if deferral_candidates:
        candidates, backend_used = deferral_candidates, deferral_backend
    else:
        candidates, backend_used = top_n_candidates(message, n=3)
    top_score = 0.0
    top_tool: str | None = None
    if candidates:
        top = candidates[0]
        top_tool = top.tool
        top_score = top.rerank_score if top.rerank_score is not None else top.score

    from app.core.routing_observability import record_deferral

    entry = record_deferral(message, candidates, backend_used)
    log_step(
        logger,
        "tool_router.deferral",
        "miss",
        level=logging.INFO if entry.near_miss else logging.DEBUG,
        backend=backend_used,
        near_miss=entry.near_miss,
        top_tool=top_tool,
        top_score=top_score,
    )
    log_step(logger, "tool_router", "miss", level=logging.DEBUG, backend="token")
    return None


def _aggregate_tool_matches(
    items: list[tuple[_Example, float, Optional[float]]],
    backend: str,
    n: int,
) -> list[ToolMatch]:
    """Keep the best-scoring example per tool and return the top *n* tools."""
    best: dict[str, ToolMatch] = {}
    for ex, embed_score, rerank_score in items:
        rank_score = rerank_score if rerank_score is not None else embed_score
        prev = best.get(ex.tool)
        prev_rank = (prev.rerank_score or prev.score) if prev else -1.0
        if prev is None or rank_score > prev_rank:
            best[ex.tool] = ToolMatch(
                tool=ex.tool,
                score=embed_score,
                hint=ex.hint,
                utterance=ex.utterance,
                backend=backend,
                rerank_score=rerank_score,
            )
    return sorted(
        best.values(),
        key=lambda match: match.rerank_score if match.rerank_score is not None else match.score,
        reverse=True,
    )[:n]


def top_n_candidates(message: str, n: int = 3) -> tuple[list[ToolMatch], str]:
    """Return top-N tool candidates using the same backend chain as classify_tool.

    Unlike :func:`top_n_tools`, this mirrors rerank → embedding → token priority
    and is intended for deferral observability rather than CI-stable debugging.
    """
    if not settings.tool_router_enabled:
        return [], "disabled"

    if not _index_built:
        build_index()

    backend_setting = settings.tool_router_backend.lower()
    use_embed = (
        backend_setting == "embedding"
        or (backend_setting == "auto" and _embed_available)
    )

    if (
        use_embed
        and len(_embed_backend) > 0
        and settings.tool_router_rerank_enabled
        and _rerank_available
    ):
        candidates = _embed_backend.top_k(
            message,
            k=settings.tool_router_rerank_top_k,
            floor=0.0,
        )
        if candidates:
            from app.core.rerank import rerank_documents

            try:
                utterances = [ex.utterance for ex, _ in candidates]
                rerank_scores = rerank_documents(
                    message,
                    utterances,
                    model=settings.tool_router_rerank_model,
                    batch_size=32,
                )
                if len(rerank_scores) == len(candidates):
                    scored = [
                        (ex, embed_score, rerank_score)
                        for (ex, embed_score), rerank_score in zip(candidates, rerank_scores)
                    ]
                    return _aggregate_tool_matches(scored, "rerank", n), "rerank"
            except Exception as exc:
                logger.warning("top_n_candidates rerank failed: %s", exc)

    if use_embed and len(_embed_backend) > 0:
        candidates = _embed_backend.top_k(message, k=max(n * 5, 20), floor=0.0)
        if candidates:
            scored = [(ex, score, None) for ex, score in candidates]
            return _aggregate_tool_matches(scored, "embedding", n), "embedding"

    return top_n_tools(message, n=n), "token"


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

    from app.core.lexicon import normalize_for_routing

    normalized = normalize_for_routing(message)
    tokens = tokenize(normalized)
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
