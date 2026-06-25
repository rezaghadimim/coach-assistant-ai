"""Embedding provider types and profile resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

EmbedProviderName = Literal["ollama", "openrouter", "openai"]
CorpusKind = Literal["framework", "collection"]


@dataclass(frozen=True)
class EmbedProfile:
    """Identifies which embedding model produced a vector."""

    provider: EmbedProviderName
    model: str
    dimensions: int = 0
    use_e5_prefix: bool = False

    @property
    def profile_id(self) -> str:
        short = self.model.split("/")[-1] if "/" in self.model else self.model
        return f"{self.provider}/{short}"


class EmbedProvider(Protocol):
    """Protocol for text embedding backends."""

    profile: EmbedProfile

    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...

    def probe(self) -> bool: ...
