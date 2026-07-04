"""Coach Assistant AI — Application entry point."""

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

import uvicorn
from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.auth import require_api_key
from app.api.briefing import router as briefing_router
from app.api.chat import router as chat_router
from app.api.collections import router as collections_router
from app.api.ingest import router as ingest_router
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


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AI-powered coaching assistant — manage clients, track stories, and deliver actionable coaching guidance.",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")

_auth = [Depends(require_api_key)]

app.include_router(chat_router, prefix="/api", tags=["chat"], dependencies=_auth)
app.include_router(ingest_router, prefix="/api", tags=["ingest"], dependencies=_auth)
app.include_router(collections_router, prefix="/api", tags=["collections"], dependencies=_auth)
app.include_router(briefing_router, prefix="/api", tags=["briefing"], dependencies=_auth)
app.include_router(users_router, prefix="/api", tags=["users"], dependencies=_auth)
app.include_router(tools_router, prefix="/api", tags=["tools"], dependencies=_auth)
app.include_router(openai_compat_router, tags=["openai-compat"], dependencies=_auth)


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
        "model": settings.ollama_embed_model,
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


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, log_config=None)
