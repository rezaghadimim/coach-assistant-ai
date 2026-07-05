"""Tests for application settings normalization."""

from unittest.mock import patch

from app.core.config import Settings


class TestOllamaBaseUrlNormalization:
    def test_host_docker_internal_rewritten_outside_docker(self):
        with patch.object(Settings, "_running_in_docker", return_value=False):
            settings = Settings(ollama_base_url="http://host.docker.internal:11434")
        assert settings.ollama_base_url == "http://localhost:11434"

    def test_host_docker_internal_kept_inside_docker(self):
        with patch.object(Settings, "_running_in_docker", return_value=True):
            settings = Settings(ollama_base_url="http://host.docker.internal:11434")
        assert settings.ollama_base_url == "http://host.docker.internal:11434"

    def test_localhost_unchanged(self):
        with patch.object(Settings, "_running_in_docker", return_value=False):
            settings = Settings(ollama_base_url="http://localhost:11434")
        assert settings.ollama_base_url == "http://localhost:11434"


class TestEmbedModelSettings:
    def test_ollama_embed_model_alias_maps_to_rag_embed_model(self):
        settings = Settings(ollama_embed_model="custom/embed-model")
        assert settings.rag_embed_model == "custom/embed-model"


class TestSeparateServiceAddresses:
    """LLM, embedding, and reranker each have an independently settable address."""

    def test_defaults_are_independent(self):
        settings = Settings()
        assert settings.ollama_base_url == "http://localhost:11434"
        assert settings.rag_embed_provider == "ollama"
        assert settings.rag_embed_base_url == ""
        assert settings.openai_base_url == "https://api.openai.com/v1"
        assert settings.rag_rerank_provider == "local"
        assert settings.rag_rerank_base_url == ""

    def test_can_point_each_service_at_a_different_host(self):
        settings = Settings(
            ollama_base_url="http://llm-server:11434",
            rag_embed_provider="openai",
            rag_embed_base_url="http://embed-server:8081/v1",
            rag_rerank_provider="tei",
            rag_rerank_base_url="http://rerank-server:8080",
        )
        assert settings.ollama_base_url == "http://llm-server:11434"
        assert settings.rag_embed_provider == "openai"
        assert settings.rag_embed_base_url == "http://embed-server:8081/v1"
        assert settings.rag_rerank_provider == "tei"
        assert settings.rag_rerank_base_url == "http://rerank-server:8080"
