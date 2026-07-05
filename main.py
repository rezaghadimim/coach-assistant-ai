"""Coach Assistant AI — Application entry point."""

import asyncio
import logging
import time
from contextlib import asynccontextmanager, suppress

import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app.api.auth import require_api_key
from app.api.briefing import router as briefing_router
from app.api.chat import router as chat_router
from app.api.collections import router as collections_router
from app.api.ingest import router as ingest_router
from app.api.metrics import observe_request_duration
from app.api.metrics import router as metrics_router
from app.api.openai_compat import router as openai_compat_router
from app.api.tools import router as tools_router
from app.api.users import router as users_router
from app.core.config import settings
from app.core.observability import setup_logging

setup_logging()

logger = logging.getLogger(__name__)


async def _warm_rerank_background() -> None:
    """Load the cross-encoder after startup so /health/live is not blocked by HF downloads."""
    from app.core.rerank import fastembed_installed, probe_rerank_model

    if not fastembed_installed():
        logger.warning(
            "rag: rerank enabled but fastembed is not installed — "
            "reranking disabled (pip install fastembed). Falling back to stage-1 order."
        )
        return

    available = await asyncio.to_thread(probe_rerank_model)
    logger.info(
        "rag: rerank %s | model=%s (local cross-encoder via fastembed)",
        "ready" if available else "unavailable — falling back to stage-1",
        settings.rag_rerank_model,
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.tool_router_enabled:
        from app.core.tool_router import build_index
        count = build_index()
        logger.info("tool router: index ready (%d examples)", count)

    if settings.rag_enabled:
        from app.core.knowledge_paths import knowledge_starter_dir
        from app.knowledge.jobs import process_pending_sources
        from app.rag.retriever import ingest_and_index_knowledge
        from app.core.embeddings import probe_embed_model

        if knowledge_starter_dir().exists():
            process_pending_sources()
            use_embed = settings.rag_backend == "embedding" or (
                settings.rag_backend == "auto" and probe_embed_model(corpus="framework")
            )
            docs, chunks = ingest_and_index_knowledge(
                chunk_size=settings.rag_chunk_size,
                chunk_overlap=settings.rag_chunk_overlap,
                embed=use_embed,
                cache_path=settings.rag_index_cache_path if use_embed else None,
                include_collections=True,
            )
            logger.info(
                "rag: index ready | backend=%s docs=%d chunks=%d",
                "embedding" if use_embed else "token",
                docs,
                chunks,
            )
        else:
            logger.warning(
                "rag: starter dir %r not found — index empty",
                settings.rag_knowledge_starter_dir,
            )

    rerank_warm_task: asyncio.Task | None = None
    if settings.rag_rerank_enabled:
        rerank_warm_task = asyncio.create_task(_warm_rerank_background())

    yield

    if rerank_warm_task is not None:
        rerank_warm_task.cancel()
        with suppress(asyncio.CancelledError):
            await rerank_warm_task

    # Close pooled provider HTTP clients (REL-04).
    from app.core.llm_providers.http import close_all
    await close_all()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AI-powered coaching assistant — manage clients, track stories, and deliver actionable coaching guidance.",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    openapi_url="/openapi.json" if settings.debug else None,
)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.middleware("http")
async def _record_request_duration(request: Request, call_next):
    """Record every request's wall-clock duration for /metrics (IMP-03)."""
    start = time.perf_counter()
    try:
        return await call_next(request)
    finally:
        observe_request_duration(time.perf_counter() - start)


_auth = [Depends(require_api_key)]

app.include_router(chat_router, prefix="/api", tags=["chat"], dependencies=_auth)
app.include_router(ingest_router, prefix="/api", tags=["ingest"], dependencies=_auth)
app.include_router(collections_router, prefix="/api", tags=["collections"], dependencies=_auth)
app.include_router(briefing_router, prefix="/api", tags=["briefing"], dependencies=_auth)
app.include_router(users_router, prefix="/api", tags=["users"], dependencies=_auth)
app.include_router(tools_router, prefix="/api", tags=["tools"], dependencies=_auth)
app.include_router(openai_compat_router, tags=["openai-compat"], dependencies=_auth)
# Prometheus scrape endpoint — unauthenticated, mirroring /health's posture.
app.include_router(metrics_router, tags=["metrics"])


@app.get("/health/live")
async def health_live():
    """Lightweight liveness probe for Docker/orchestrators (no external I/O)."""
    return {"status": "ok"}


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


_EMBED_PROBE_TTL_SECONDS = 60.0

# Module-level embed-probe cache: (result, expires_at) — mirrors probe_openrouter.
_embed_probe_cache: tuple[bool, float] = (False, 0.0)


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


@app.get("/health")
async def health_check():
    """Report application status and per-layer availability.

    ``status`` is ``"ok"`` only when every enabled layer is actually usable;
    otherwise ``"degraded"`` with a human-readable ``issues`` list. Monitors
    should alert on ``status != "ok"`` (see docs/BENCHMARKS.md).
    """
    from app.core.model_registry import (
        LOCAL_MODEL_ID,
        openrouter_availability_reason,
        openrouter_models,
        probe_openrouter,
    )

    issues: list[str] = []

    ollama_ok = await _probe_ollama_server()
    if not ollama_ok:
        issues.append(f"ollama unreachable at {settings.ollama_base_url}")

    cloud_ok = await probe_openrouter()
    openrouter_info: dict = {
        "models": openrouter_models(),
        "available": cloud_ok,
    }
    if not cloud_ok:
        openrouter_info["reason"] = openrouter_availability_reason()
        # Optional provider: unavailability is only an issue when configured.
        if settings.openrouter_api_key:
            issues.append("openrouter configured but unavailable")

    from app.core.embeddings import probe_embed_model

    embed_available = probe_embed_model() if settings.tool_router_enabled else False
    embed_info = {
        "model": settings.rag_embed_model,
        "available": embed_available,
        "backend": settings.tool_router_backend,
        "enabled": settings.tool_router_enabled,
    }
    if (
        settings.tool_router_enabled
        and settings.tool_router_backend == "embedding"
        and not embed_available
    ):
        # "auto" degrades to token silently by design; forced embedding does not.
        issues.append("embedding backend forced but embed model unavailable")

    from app.core.routing_observability import get_stats as routing_stats

    tool_router_info: dict = {
        "enabled": settings.tool_router_enabled,
        "backend": settings.tool_router_backend,
    }
    if settings.tool_router_enabled:
        tool_router_info.update(routing_stats())

    rerank_info: dict = {
        "enabled": settings.rag_rerank_enabled,
        "model": settings.rag_rerank_model,
        "backend": "fastembed",
        "available": False,
    }
    if settings.rag_rerank_enabled:
        from app.core.rerank import rerank_probe_cached

        cached = rerank_probe_cached()
        if cached is None:
            # Background warmup is still running — do not trigger a blocking load.
            rerank_info["available"] = False
            rerank_info["status"] = "warming"
        else:
            rerank_info["available"] = cached is True
            if cached is False:
                issues.append(
                    "reranker enabled but cross-encoder failed to load "
                    "(retrieval falls back to stage-1)"
                )

    return {
        "status": "ok" if not issues else "degraded",
        "issues": issues,
        "default_model": LOCAL_MODEL_ID,
        "providers": {
            "ollama": {
                "model": settings.ollama_model,
                "available": ollama_ok,
            },
            "openrouter": openrouter_info,
        },
        "embeddings": embed_info,
        "tool_router": tool_router_info,
        "rerank": rerank_info,
    }


async def _layer_availability() -> dict[str, bool]:
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


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, log_config=None)
