"""Ollama embedding client for tool routing.

Provides synchronous embedding via the Ollama ``POST /api/embeddings`` endpoint.
No new Python ML dependencies — only ``httpx`` (already required).

Supports multilingual-e5-small prefix convention:
  - queries  → ``"query: {text}"``
  - passages → ``"passage: {text}"``

This is intentionally a thin, synchronous client (unlike the async chat
providers) because embedding calls happen at index-build time (startup / reindex)
and at classify time (blocking, ~10–50 ms per query on CPU).
"""

from __future__ import annotations

import logging
import math
from typing import Literal

import httpx

from app.core.config import settings
from app.core.observability import log_step

logger = logging.getLogger(__name__)

_InputType = Literal["query", "passage"]

# multilingual-e5-small uses a 512 *subword* token context. RAG chunks are sized
# in whitespace-delimited words; markdown-heavy text can exceed 512 subword tokens
# well before 350 words (see cbt_for_coaching.md / motivational_interviewing.md).
DEFAULT_EMBED_MAX_WORDS = 300
_EMBED_RETRY_WORD_LIMITS = (300, 240, 180)


def _truncate_for_embed(text: str, *, max_words: int | None = None) -> str:
    """Trim text so prefixed input stays within the embed model context window."""
    limit = max_words if max_words is not None else DEFAULT_EMBED_MAX_WORDS
    words = text.split()
    if len(words) <= limit:
        return text
    logger.debug("truncating embed input from %d to %d words", len(words), limit)
    return " ".join(words[:limit])


def _apply_prefix(text: str, input_type: _InputType) -> str:
    if not settings.tool_router_use_e5_prefix:
        return text
    return f"{input_type}: {text}"


def embed_texts(
    texts: list[str],
    *,
    input_type: _InputType = "passage",
    model: str | None = None,
    max_words: int | None = None,
) -> list[list[float]]:
    """Embed a list of texts using Ollama and return a list of float vectors.

    Sends one HTTP request per text (Ollama /api/embeddings is single-input).
    Callers should batch at index-build time, not per chat message.

    Args:
        texts: Raw text strings (prefix is applied automatically).
        input_type: ``"query"`` for user messages, ``"passage"`` for indexed examples.
        model: Override the embed model (defaults to ``settings.ollama_embed_model``).

    Returns:
        A list of embedding vectors, one per input text.

    Raises:
        httpx.HTTPError: When Ollama is unreachable or returns an error status.
    """
    embed_model = model or settings.ollama_embed_model
    results: list[list[float]] = []
    word_limits = _word_limits_for_embed(max_words)

    with httpx.Client(
        base_url=settings.ollama_base_url,
        timeout=settings.ollama_timeout,
    ) as client:
        for text in texts:
            results.append(
                _embed_one(client, embed_model, text, input_type, word_limits)
            )

    return results


def _word_limits_for_embed(max_words: int | None) -> tuple[int, ...]:
    if max_words is None:
        return _EMBED_RETRY_WORD_LIMITS
    smaller = tuple(
        limit
        for limit in _EMBED_RETRY_WORD_LIMITS
        if limit < max_words
    )
    return (max_words, *smaller)


def _context_length_error(response: httpx.Response) -> bool:
    if response.status_code != 500:
        return False
    try:
        message = response.json().get("error", "")
    except ValueError:
        message = response.text
    return "context length" in message.lower()


def _embed_one(
    client: httpx.Client,
    embed_model: str,
    text: str,
    input_type: _InputType,
    word_limits: tuple[int, ...],
) -> list[float]:
    last_response: httpx.Response | None = None
    for limit in word_limits:
        trimmed = _truncate_for_embed(text, max_words=limit)
        prefixed = _apply_prefix(trimmed, input_type)
        response = client.post(
            "/api/embeddings",
            json={"model": embed_model, "prompt": prefixed},
        )
        if response.is_success:
            return response.json()["embedding"]
        if _context_length_error(response):
            last_response = response
            logger.debug(
                "embed input exceeded context at %d words — retrying smaller",
                limit,
            )
            continue
        response.raise_for_status()

    if last_response is not None:
        last_response.raise_for_status()
    raise RuntimeError("embed failed without a response")


def embed_query(text: str, *, model: str | None = None) -> list[float]:
    """Embed a single query string (applies ``query:`` prefix for E5 models)."""
    return embed_texts([text], input_type="query", model=model)[0]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two dense float vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def probe_embed_model(*, model: str | None = None) -> bool:
    """Return True when the Ollama embed model is reachable and responsive.

    Used by the ``auto`` backend to decide whether to use embedding or fall
    back to the token backend.
    """
    try:
        embed_texts(["ping"], input_type="query", model=model)
        log_step(logger, "embed.probe", "ok", level=logging.DEBUG,
                 model=model or settings.ollama_embed_model)
        return True
    except Exception as exc:
        log_step(logger, "embed.probe", "fail", level=logging.DEBUG,
                 model=model or settings.ollama_embed_model, exc=type(exc).__name__)
        return False
