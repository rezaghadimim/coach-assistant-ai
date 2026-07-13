"""Per-layer health probes shared by /health and /metrics."""

import asyncio
import time

from app.core.config import settings

_EMBED_PROBE_TTL_SECONDS = 60.0

# Module-level embed-probe cache: (result, expires_at) — mirrors probe_openrouter.
_embed_probe_cache: tuple[bool, float] = (False, 0.0)


async def _probe_ollama_server() -> bool:
    """Cheap reachability probe for the local Ollama server (no model load)."""
    import httpx

    try:
        async with httpx.AsyncClient(
            base_url=settings.ollama_base_url, timeout=3.0
        ) as client:
            response = await client.get("/api/version")
            return response.is_success
    except Exception:
        return False


async def _probe_embed_cached() -> bool:
    """TTL-cached embed-model probe, run off the event loop.

    ``probe_embed_model`` is synchronous and performs a real embedding call,
    so unauthenticated /metrics scrapes must not run it inline per request.
    """
    global _embed_probe_cache

    cached_result, expires_at = _embed_probe_cache
    if time.monotonic() < expires_at:
        return cached_result

    from app.core.embeddings import probe_embed_model

    result = await asyncio.to_thread(probe_embed_model)
    _embed_probe_cache = (result, time.monotonic() + _EMBED_PROBE_TTL_SECONDS)
    return result


async def layer_availability() -> dict[str, bool]:
    """Per-layer availability booleans, shared by /metrics (IMP-03).

    Mirrors the per-layer probes behind /health so the two surfaces report the
    same view. Returns only booleans — no message content or identifiers.
    """
    from app.core.model_registry import probe_openrouter

    ollama_ok = await _probe_ollama_server()
    cloud_ok = await probe_openrouter()
    embed_ok = await _probe_embed_cached() if settings.tool_router_enabled else False

    rerank_ok = False
    if settings.rag_rerank_enabled:
        from app.core.rerank import rerank_probe_cached

        rerank_ok = rerank_probe_cached() is True

    return {
        "ollama": ollama_ok,
        "openrouter": cloud_ok,
        "embeddings": embed_ok,
        "tool_router": settings.tool_router_enabled,
        "rerank": rerank_ok,
    }
