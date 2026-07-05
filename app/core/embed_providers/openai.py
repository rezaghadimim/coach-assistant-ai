"""OpenAI embedding provider."""

from __future__ import annotations

import logging

import httpx

from app.core.config import settings
from app.core.embed_providers.types import EmbedProfile

logger = logging.getLogger(__name__)

_DEFAULT_DIMENSIONS = 1536
_BATCH_SIZE = 32
_DEFAULT_OPENAI_BASE = "https://api.openai.com/v1"


def _resolved_base_url() -> str:
    """Address actually used: RAG_EMBED_BASE_URL wins, else openai_base_url."""
    return (settings.rag_embed_base_url or settings.openai_base_url).rstrip("/")


def _is_default_host() -> bool:
    return _resolved_base_url() == _DEFAULT_OPENAI_BASE


class OpenAIEmbedProvider:
    """Embeddings via an OpenAI-compatible ``POST /embeddings`` endpoint.

    Defaults to api.openai.com. Set ``rag_embed_base_url`` (preferred) or
    ``openai_base_url`` to target a self-hosted OpenAI-compatible server
    (e.g. TEI) on a different machine. ``openai_api_key`` is only required
    for the real OpenAI host.
    """

    def __init__(self, *, model: str, dimensions: int = _DEFAULT_DIMENSIONS) -> None:
        self.profile = EmbedProfile(
            provider="openai",
            model=model,
            dimensions=dimensions,
            use_e5_prefix=False,
        )

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return self._embed_batch(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._embed_batch([text])[0]

    def probe(self) -> bool:
        if _is_default_host() and not settings.openai_api_key:
            return False
        try:
            self.embed_query("ping")
            return True
        except Exception as exc:
            logger.debug("openai embed probe failed: %s", exc)
            return False

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        if _is_default_host() and not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        if not texts:
            return []

        headers = {"Content-Type": "application/json"}
        if settings.openai_api_key:
            headers["Authorization"] = f"Bearer {settings.openai_api_key}"

        base_url = _resolved_base_url()
        vectors: list[list[float]] = []
        with httpx.Client(timeout=settings.openrouter_timeout) as client:
            for start in range(0, len(texts), _BATCH_SIZE):
                batch = texts[start : start + _BATCH_SIZE]
                response = client.post(
                    f"{base_url}/embeddings",
                    headers=headers,
                    json={"model": self.profile.model, "input": batch},
                )
                response.raise_for_status()
                payload = response.json()
                data = sorted(payload["data"], key=lambda item: item["index"])
                vectors.extend(item["embedding"] for item in data)
        return vectors
