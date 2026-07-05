"""Embedding provider factory."""

from __future__ import annotations

from app.core.config import settings
from app.core.embed_providers.openai import OpenAIEmbedProvider
from app.core.embed_providers.ollama import OllamaEmbedProvider
from app.core.embed_providers.openrouter import OpenRouterEmbedProvider
from app.core.embed_providers.types import CorpusKind, EmbedProfile, EmbedProvider

_KNOWN_DIMENSIONS: dict[str, int] = {
    "karuniaperjuangan/multilingual-e5-small": 384,
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "openai/text-embedding-3-small": 1536,
    "openai/text-embedding-3-large": 3072,
}


def _dimensions_for_model(model: str) -> int:
    return _KNOWN_DIMENSIONS.get(model, _KNOWN_DIMENSIONS.get(model.split("/")[-1], 0))


def embed_profile_for_corpus(corpus: CorpusKind) -> EmbedProfile:
    """Resolve the embed profile for framework vs collection corpora."""

    if corpus == "collection":
        provider = settings.rag_collection_embed_provider or settings.rag_embed_provider
        model = settings.rag_collection_embed_model or settings.rag_embed_model
    else:
        provider = settings.rag_embed_provider
        model = settings.rag_embed_model

    return EmbedProfile(
        provider=provider,  # type: ignore[arg-type]
        model=model,
        dimensions=_dimensions_for_model(model),
        use_e5_prefix=provider == "ollama" and settings.tool_router_use_e5_prefix,
    )


def get_embed_provider(profile: EmbedProfile | None = None, *, corpus: CorpusKind = "framework") -> EmbedProvider:
    """Return an embedding provider for the given profile or corpus defaults."""
    resolved = profile or embed_profile_for_corpus(corpus)
    if resolved.provider == "openrouter":
        return OpenRouterEmbedProvider(
            model=resolved.model,
            dimensions=resolved.dimensions or _dimensions_for_model(resolved.model),
        )
    if resolved.provider == "openai":
        return OpenAIEmbedProvider(
            model=resolved.model,
            dimensions=resolved.dimensions or _dimensions_for_model(resolved.model),
        )
    return OllamaEmbedProvider(
        model=resolved.model,
        use_e5_prefix=resolved.use_e5_prefix,
        dimensions=resolved.dimensions or 384,
    )
