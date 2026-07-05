"""Tests for embedding provider factory."""

from unittest.mock import patch

from app.core.embed_providers import embed_profile_for_corpus, get_embed_provider
from app.core.embed_providers.openai import OpenAIEmbedProvider
from app.core.embed_providers.ollama import OllamaEmbedProvider


def test_framework_profile_defaults_to_ollama() -> None:
    profile = embed_profile_for_corpus("framework")
    provider = get_embed_provider(profile)
    assert isinstance(provider, OllamaEmbedProvider)
    assert profile.provider == "ollama"


def test_collection_profile_inherits_framework_ollama() -> None:
    profile = embed_profile_for_corpus("collection")
    provider = get_embed_provider(profile)
    assert isinstance(provider, OllamaEmbedProvider)
    assert profile.provider == "ollama"


def test_openai_provider_when_configured() -> None:
    from app.core.config import settings

    with patch.object(settings, "rag_collection_embed_provider", "openai"):
        with patch.object(settings, "rag_collection_embed_model", "text-embedding-3-small"):
            profile = embed_profile_for_corpus("collection")
            provider = get_embed_provider(profile)
            assert isinstance(provider, OpenAIEmbedProvider)
