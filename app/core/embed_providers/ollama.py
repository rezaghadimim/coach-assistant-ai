"""Ollama embedding provider."""

from __future__ import annotations

import logging

import httpx

from app.core.embed_providers.types import EmbedProfile

logger = logging.getLogger(__name__)

_EMBED_RETRY_WORD_LIMITS = (300, 240, 180)


class OllamaEmbedProvider:
    """Dense embeddings via Ollama ``POST /api/embeddings``."""

    def __init__(
        self,
        *,
        model: str | None = None,
        use_e5_prefix: bool | None = None,
        dimensions: int = 384,
    ) -> None:
        from app.core.config import settings

        self.profile = EmbedProfile(
            provider="ollama",
            model=model or settings.ollama_embed_model,
            dimensions=dimensions,
            use_e5_prefix=(
                use_e5_prefix
                if use_e5_prefix is not None
                else settings.tool_router_use_e5_prefix
            ),
        )

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return self._embed_many(texts, input_type="passage")

    def embed_query(self, text: str) -> list[float]:
        return self._embed_many([text], input_type="query")[0]

    def probe(self) -> bool:
        try:
            self.embed_query("ping")
            return True
        except Exception as exc:
            logger.debug("ollama embed probe failed: %s", exc)
            return False

    def _embed_many(self, texts: list[str], *, input_type: str) -> list[list[float]]:
        from app.core.config import settings

        results: list[list[float]] = []
        with httpx.Client(
            base_url=settings.ollama_base_url,
            timeout=settings.ollama_timeout,
        ) as client:
            for text in texts:
                results.append(self._embed_one(client, text, input_type))
        return results

    def _embed_one(
        self,
        client: httpx.Client,
        text: str,
        input_type: str,
    ) -> list[float]:
        last_response: httpx.Response | None = None
        for limit in _EMBED_RETRY_WORD_LIMITS:
            trimmed = _truncate_words(text, limit)
            prefixed = self._apply_prefix(trimmed, input_type)
            response = client.post(
                "/api/embeddings",
                json={"model": self.profile.model, "prompt": prefixed},
            )
            if response.is_success:
                return response.json()["embedding"]
            if _context_length_error(response):
                last_response = response
                continue
            response.raise_for_status()
        if last_response is not None:
            last_response.raise_for_status()
        raise RuntimeError("ollama embed failed without a response")

    def _apply_prefix(self, text: str, input_type: str) -> str:
        if not self.profile.use_e5_prefix:
            return text
        return f"{input_type}: {text}"


def _truncate_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])


def _context_length_error(response: httpx.Response) -> bool:
    if response.status_code != 500:
        return False
    try:
        message = response.json().get("error", "")
    except ValueError:
        message = response.text
    return "context length" in message.lower()
