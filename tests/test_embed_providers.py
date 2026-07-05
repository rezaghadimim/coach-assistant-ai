"""Tests for embedding provider factory."""

from unittest.mock import MagicMock, patch

from app.core.embed_providers import embed_profile_for_corpus, get_embed_provider
from app.core.embed_providers.openai import OpenAIEmbedProvider
from app.core.embed_providers.ollama import OllamaEmbedProvider
from app.core.embed_providers.openrouter import OpenRouterEmbedProvider


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


def test_rag_embed_base_url_overrides_ollama_default() -> None:
    from app.core.config import settings

    response = MagicMock()
    response.is_success = True
    response.json.return_value = {"embedding": [0.1]}
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.post = MagicMock(return_value=response)

    provider = OllamaEmbedProvider(model="e5-small")
    with patch.object(settings, "rag_embed_base_url", "http://second-server:11434"), \
         patch("app.core.embed_providers.ollama.httpx.Client", return_value=client) as mock_ctor:
        provider.embed_query("hello")

    assert mock_ctor.call_args.kwargs["base_url"] == "http://second-server:11434"


def test_rag_embed_base_url_falls_back_to_ollama_base_url_when_unset() -> None:
    from app.core.config import settings

    response = MagicMock()
    response.is_success = True
    response.json.return_value = {"embedding": [0.1]}
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.post = MagicMock(return_value=response)

    provider = OllamaEmbedProvider(model="e5-small")
    with patch.object(settings, "rag_embed_base_url", ""), \
         patch.object(settings, "ollama_base_url", "http://localhost:11434"), \
         patch("app.core.embed_providers.ollama.httpx.Client", return_value=client) as mock_ctor:
        provider.embed_query("hello")

    assert mock_ctor.call_args.kwargs["base_url"] == "http://localhost:11434"


def test_rag_embed_base_url_overrides_openrouter_default() -> None:
    from app.core.config import settings

    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {"data": [{"index": 0, "embedding": [0.2]}]}
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.post = MagicMock(return_value=response)

    provider = OpenRouterEmbedProvider(model="openai/text-embedding-3-small")
    with patch.object(settings, "openrouter_api_key", "test-key"), \
         patch.object(settings, "rag_embed_base_url", "http://second-server:9090"), \
         patch("app.core.embed_providers.openrouter.httpx.Client", return_value=client) as mock_ctor:
        provider.embed_query("hello")

    assert mock_ctor.call_args.kwargs["base_url"] == "http://second-server:9090"
