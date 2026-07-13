"""On-disk embedding cache I/O for RAG retrieval indices.

Cache envelope (JSON): ``{version, model, dim, chunks}`` where *chunks* maps
``embed_profile_id::chunk_id::sha256(text)[:16]`` → embedding vector.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Literal

from app.core.embed_providers.types import EmbedProfile
from app.core.observability import log_step
from app.rag.ingest import DocumentChunk

logger = logging.getLogger(__name__)

CorpusKind = Literal["framework", "collection"]

# Bumped if the on-disk cache envelope shape changes in an incompatible way.
CACHE_FORMAT_VERSION = 1


def corpus_cache_path(cache_path: str, corpus: CorpusKind) -> str:
    """Per-corpus cache file derived from the configured path.

    The framework corpus keeps the configured path unchanged (backward
    compatible with existing caches); the collection corpus writes to a
    ``<stem>.collection<ext>`` sibling so the two never overwrite each other.
    """
    if corpus == "framework":
        return cache_path
    path = Path(cache_path)
    return str(path.with_name(f"{path.stem}.{corpus}{path.suffix}"))


def cache_key(chunk: DocumentChunk) -> str:
    text_hash = hashlib.sha256(chunk.text.encode()).hexdigest()[:16]
    return f"{chunk.embed_profile_id}::{chunk.chunk_id}::{text_hash}"


def load_cache(cache_path: str, profile: EmbedProfile | None = None) -> dict[str, list[float]]:
    """Load the on-disk embedding cache, discarding it on a model/dim mismatch.

    The cache file stores an identity header (``model`` + ``dim``) alongside
    the vectors. If *profile* is given and does not match the header, the
    cache is stale (e.g. the operator swapped ``rag_embed_model``) and must
    not be reused, since the vectors would have the wrong dimensionality or
    come from a different embedding space entirely.
    """
    path = Path(cache_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("rag: could not load embedding cache %s: %s", cache_path, exc)
        return {}

    if not isinstance(data, dict):
        return {}

    # Legacy bare-dict cache (no identity header): treat as stale so it is
    # rebuilt with a proper header rather than silently reused.
    if "chunks" not in data:
        if profile is not None:
            log_step(
                logger,
                "rag.cache",
                "stale",
                reason="legacy_format_no_header",
                cache_path=cache_path,
            )
            return {}
        return data

    chunks = data.get("chunks")
    if not isinstance(chunks, dict):
        return {}

    if profile is not None:
        stored_model = data.get("model")
        stored_dim = data.get("dim")
        if stored_model != profile.model or stored_dim != profile.dimensions:
            log_step(
                logger,
                "rag.cache",
                "stale",
                reason="model_or_dim_mismatch",
                cache_path=cache_path,
                stored_model=stored_model,
                current_model=profile.model,
                stored_dim=stored_dim,
                current_dim=profile.dimensions,
            )
            return {}

    return chunks


def save_cache(
    cache_path: str,
    cache: dict[str, list[float]],
    profile: EmbedProfile | None = None,
) -> None:
    path = Path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict = {"version": CACHE_FORMAT_VERSION, "chunks": cache}
    if profile is not None:
        payload["model"] = profile.model
        payload["dim"] = profile.dimensions
    try:
        path.write_text(json.dumps(payload), encoding="utf-8")
    except Exception as exc:
        logger.warning("rag: could not write embedding cache %s: %s", cache_path, exc)
