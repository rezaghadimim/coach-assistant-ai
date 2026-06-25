"""Embedding client facade over pluggable providers.

Backward-compatible exports used by RAG, tool router, and tests.
"""

from __future__ import annotations

import math

from app.core.config import settings
from app.core.embed_providers import embed_profile_for_corpus, get_embed_provider
from app.core.embed_providers.types import CorpusKind, EmbedProfile
from app.core.observability import log_step

import logging

logger = logging.getLogger(__name__)

DEFAULT_EMBED_MAX_WORDS = 300


def embed_texts(
    texts: list[str],
    *,
    input_type: str = "passage",
    model: str | None = None,
    max_words: int | None = None,
    corpus: CorpusKind = "framework",
    profile: EmbedProfile | None = None,
) -> list[list[float]]:
    """Embed texts using the configured provider for *corpus*."""
    if max_words is not None:
        from app.core.embed_providers.ollama import _truncate_words

        texts = [_truncate_words(text, max_words) for text in texts]
    resolved_profile = profile or embed_profile_for_corpus(corpus)
    if model is not None:
        resolved_profile = EmbedProfile(
            provider=resolved_profile.provider,
            model=model,
            dimensions=resolved_profile.dimensions,
            use_e5_prefix=resolved_profile.use_e5_prefix,
        )
    provider = get_embed_provider(resolved_profile)
    if input_type == "query":
        return [provider.embed_query(text) for text in texts]
    return provider.embed_passages(texts)


def embed_query(
    text: str,
    *,
    model: str | None = None,
    corpus: CorpusKind = "framework",
    profile: EmbedProfile | None = None,
) -> list[float]:
    """Embed a single query string."""
    return embed_texts(
        [text],
        input_type="query",
        model=model,
        corpus=corpus,
        profile=profile,
    )[0]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two dense float vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def probe_embed_model(*, model: str | None = None, corpus: CorpusKind = "framework") -> bool:
    """Return True when the embed provider for *corpus* is reachable."""
    try:
        profile = embed_profile_for_corpus(corpus)
        if model is not None:
            profile = EmbedProfile(
                provider=profile.provider,
                model=model,
                dimensions=profile.dimensions,
                use_e5_prefix=profile.use_e5_prefix,
            )
        ok = get_embed_provider(profile).probe()
        log_step(
            logger,
            "embed.probe",
            "ok" if ok else "fail",
            level=logging.DEBUG,
            model=model or profile.model,
            provider=profile.provider,
        )
        return ok
    except Exception as exc:
        log_step(
            logger,
            "embed.probe",
            "fail",
            level=logging.DEBUG,
            model=model or settings.ollama_embed_model,
            exc=type(exc).__name__,
        )
        return False


# Backward-compatible re-export for tests and callers.
from app.core.embed_providers.ollama import _truncate_words as _truncate_for_embed  # noqa: E402
