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

logger = logging.getLogger(__name__)

_InputType = Literal["query", "passage"]


def _apply_prefix(text: str, input_type: _InputType) -> str:
    if not settings.tool_router_use_e5_prefix:
        return text
    return f"{input_type}: {text}"


def embed_texts(
    texts: list[str],
    *,
    input_type: _InputType = "passage",
    model: str | None = None,
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

    with httpx.Client(
        base_url=settings.ollama_base_url,
        timeout=settings.ollama_timeout,
    ) as client:
        for text in texts:
            prefixed = _apply_prefix(text, input_type)
            response = client.post(
                "/api/embeddings",
                json={"model": embed_model, "prompt": prefixed},
            )
            response.raise_for_status()
            results.append(response.json()["embedding"])

    return results


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
        return True
    except Exception as exc:
        logger.debug("embed probe failed: %s", exc)
        return False
