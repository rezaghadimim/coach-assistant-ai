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
