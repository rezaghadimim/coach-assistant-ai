"""OpenAI embedding provider."""

from __future__ import annotations

import logging

import httpx

from app.core.config import settings
from app.core.embed_providers.types import EmbedProfile

logger = logging.getLogger(__name__)

_DEFAULT_DIMENSIONS = 1536
_BATCH_SIZE = 32
_OPENAI_BASE = "https://api.openai.com/v1"


class OpenAIEmbedProvider:
    """Embeddings via OpenAI ``POST /v1/embeddings``."""

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
        if not settings.openai_api_key:
            return False
        try:
            self.embed_query("ping")
            return True
        except Exception as exc:
            logger.debug("openai embed probe failed: %s", exc)
            return False

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        if not texts:
            return []

        vectors: list[list[float]] = []
        with httpx.Client(timeout=settings.openrouter_timeout) as client:
            for start in range(0, len(texts), _BATCH_SIZE):
                batch = texts[start : start + _BATCH_SIZE]
                response = client.post(
                    f"{_OPENAI_BASE}/embeddings",
                    headers={
                        "Authorization": f"Bearer {settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={"model": self.profile.model, "input": batch},
                )
                response.raise_for_status()
                payload = response.json()
                data = sorted(payload["data"], key=lambda item: item["index"])
                vectors.extend(item["embedding"] for item in data)
        return vectors
