"""Local cross-encoder reranker for RAG stage-2 retrieval.

Runs an ONNX cross-encoder (default ``BAAI/bge-reranker-base``) **in-process**
via `fastembed <https://github.com/qdrant/fastembed>`_ — no Ollama and no
PyTorch.  Ollama cannot serve cross-encoder/reranker models at all (it loads
them as embedders and llama.cpp aborts with
``GGML_ASSERT(n_outputs_max <= cparams.n_outputs_max)``; see ollama/ollama
#3368), so reranking is done locally instead.

The model is loaded lazily as a module-level singleton.  Every entry point
degrades gracefully — callers fall back to stage-1 ordering — when fastembed is
not installed or the model cannot be loaded.
"""

from __future__ import annotations

import logging
import math
import os
import shutil
import threading
from pathlib import Path
from typing import TYPE_CHECKING

# hf-xet can leave .incomplete blobs when downloads are interrupted (e.g. Docker
# healthcheck timeout on first boot). Must be set before huggingface_hub loads.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from app.core.config import settings

if TYPE_CHECKING:
    from fastembed.rerank.cross_encoder import TextCrossEncoder

logger = logging.getLogger(__name__)

# Cross-encoder singleton plus the model name it was built with, guarded by a
# lock so concurrent requests don't load the ONNX model more than once.
_encoder: "TextCrossEncoder | None" = None
_encoder_model_name: str | None = None
_encoder_lock = threading.Lock()

# Tri-state probe result: None = not probed yet, True/False = last outcome.
_probe_ok: bool | None = None


def fastembed_installed() -> bool:
    """Return True when the optional ``fastembed`` dependency is importable."""
    try:
        import fastembed.rerank.cross_encoder  # noqa: F401
    except Exception:
        return False
    return True


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def _sigmoid(logit: float) -> float:
    """Map cross-encoder logits to (0, 1) so ``rag_min_score`` stays meaningful."""
    if logit >= 0:
        return 1.0 / (1.0 + math.exp(-logit))
    exp_x = math.exp(logit)
    return exp_x / (1.0 + exp_x)


def _hf_model_cache_dir(cache_dir: str, model_name: str) -> Path:
    return Path(cache_dir) / f"models--{model_name.replace('/', '--')}"


def _onnx_model_ready(cache_dir: str, model_name: str) -> bool:
    """Return True when no cache exists yet or a complete ONNX snapshot is present."""
    hf_dir = _hf_model_cache_dir(cache_dir, model_name)
    if not hf_dir.exists():
        return True

    snapshots = hf_dir / "snapshots"
    if not snapshots.is_dir():
        return False

    for snapshot in snapshots.iterdir():
        if not snapshot.is_dir():
            continue
        onnx_path = snapshot / "onnx" / "model.onnx"
        if onnx_path.is_file() and onnx_path.stat().st_size > 0:
            return True
    return False


def _has_incomplete_blobs(cache_dir: str, model_name: str) -> bool:
    blobs_dir = _hf_model_cache_dir(cache_dir, model_name) / "blobs"
    if not blobs_dir.is_dir():
        return False
    return any(path.name.endswith(".incomplete") for path in blobs_dir.iterdir())


def _purge_rerank_model_cache(cache_dir: str, model_name: str) -> None:
    """Delete a partial fastembed/HuggingFace cache so the ONNX model can re-download."""
    hf_dir = _hf_model_cache_dir(cache_dir, model_name)
    lock_dir = Path(cache_dir) / ".locks" / hf_dir.name
    removed = False

    if hf_dir.exists():
        shutil.rmtree(hf_dir)
        removed = True
    if lock_dir.exists():
        shutil.rmtree(lock_dir)
        removed = True

    if removed:
        logger.warning(
            "rag rerank: removed incomplete cache for %s — will re-download on next load",
            model_name,
        )


def _is_recoverable_load_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "no_suchfile" in message
        or "file doesn't exist" in message
        or "corrupted" in message
        or "files have been corrupted" in message
    )


def _get_encoder(model_name: str) -> "TextCrossEncoder":
    """Return the cached cross-encoder, loading it on first use (thread-safe)."""
    global _encoder, _encoder_model_name

    if _encoder is not None and _encoder_model_name == model_name:
        return _encoder

    with _encoder_lock:
        if _encoder is not None and _encoder_model_name == model_name:
            return _encoder
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        cache_dir = settings.rag_rerank_cache_dir or None
        cache_path = cache_dir or ""
        if cache_path and (
            not _onnx_model_ready(cache_path, model_name)
            or _has_incomplete_blobs(cache_path, model_name)
        ):
            _purge_rerank_model_cache(cache_path, model_name)

        logger.info(
            "rag rerank: loading cross-encoder %s (fastembed / ONNX, first run downloads the model)",
            model_name,
        )

        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                encoder = TextCrossEncoder(model_name=model_name, cache_dir=cache_dir)
                _encoder = encoder
                _encoder_model_name = model_name
                return encoder
            except Exception as exc:
                last_exc = exc
                if attempt == 0 and cache_path and _is_recoverable_load_error(exc):
                    _purge_rerank_model_cache(cache_path, model_name)
                    logger.info("rag rerank: retrying cross-encoder load after cache purge")
                    continue
                raise

        assert last_exc is not None
        raise last_exc


def rerank_documents(
    query: str,
    documents: list[str],
    *,
    model: str | None = None,
    batch_size: int | None = None,
    max_passage_chars: int | None = None,
) -> list[float]:
    """Return cross-encoder relevance scores for *documents* against *query*.

    Scores are aligned with the input order in the range (0, 1); higher means
    more relevant.  Raw model logits are passed through a sigmoid so they work
    with ``settings.rag_min_score``.  Raises on any failure so callers
    (``app/rag/reranker.py``) can fall back to stage-1 ordering.
    """
    global _probe_ok

    if not documents:
        return []

    model_name = model or settings.rag_rerank_model
    max_chars = (
        max_passage_chars
        if max_passage_chars is not None
        else settings.rag_rerank_max_passage_chars
    )
    batch = batch_size if batch_size is not None else settings.rag_rerank_batch_size
    batch = max(1, batch)

    passages = [_truncate(doc, max_chars) for doc in documents]

    encoder = _get_encoder(model_name)
    logits = [float(score) for score in encoder.rerank(query, passages, batch_size=batch)]
    scores = [_sigmoid(logit) for logit in logits]

    if len(scores) != len(documents):
        raise ValueError(
            f"reranker returned {len(scores)} scores for {len(documents)} documents"
        )

    _probe_ok = True
    return scores


def probe_rerank_model(*, model: str | None = None) -> bool:
    """Return True when the local cross-encoder loads and scores a probe pair.

    The result is cached: once the model has loaded successfully this returns
    immediately, so the ``/health`` endpoint stays cheap.
    """
    global _probe_ok

    if _probe_ok is True:
        return True
    if not fastembed_installed():
        if _probe_ok is None:
            logger.info("rag rerank: fastembed not installed — reranking disabled")
        _probe_ok = False
        return False

    try:
        rerank_documents("probe query", ["probe passage"], model=model, batch_size=1)
        _probe_ok = True
        return True
    except Exception as exc:
        logger.warning("rag rerank: probe failed (%s) — reranking will fall back to stage-1", exc)
        _probe_ok = False
        return False


def rerank_probe_cached() -> bool | None:
    """Return the last probe result without loading or scoring again."""
    return _probe_ok
