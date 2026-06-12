"""Coach Assistant AI — Application entry point."""

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.api.briefing import router as briefing_router
from app.api.chat import router as chat_router
from app.api.ingest import router as ingest_router
from app.api.openai_compat import router as openai_compat_router
from app.api.tools import router as tools_router
from app.api.users import router as users_router
from app.core.config import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.tool_router_enabled:
        from app.core.tool_router import build_index
        count = build_index()
        logger.info("tool router: index ready (%d examples)", count)

    if settings.rag_enabled:
        from pathlib import Path
        from app.rag.retriever import ingest_and_index_directory
        from app.core.embeddings import probe_embed_model

        docs_dir = settings.rag_docs_dir
        if Path(docs_dir).exists():
            use_embed = settings.rag_backend == "embedding" or (
                settings.rag_backend == "auto" and probe_embed_model()
            )
            docs, chunks = ingest_and_index_directory(
                docs_dir,
                chunk_size=settings.rag_chunk_size,
                chunk_overlap=settings.rag_chunk_overlap,
                embed=use_embed,
                cache_path=settings.rag_index_cache_path if use_embed else None,
            )
            logger.info(
                "rag: index ready | backend=%s docs=%d chunks=%d",
                "embedding" if use_embed else "token",
                docs,
                chunks,
            )
        else:
            logger.warning("rag: docs_dir %r not found — index empty", docs_dir)

        if settings.rag_rerank_enabled:
            from app.rag.reranker import probe_rerank_model
            if probe_rerank_model():
                logger.info("rag: rerank ready | model=%s", settings.rag_rerank_model)
            else:
                logger.warning(
                    "rag: rerank unavailable — falling back to bi-encoder order"
                    " (install with: uv sync --group rag-rerank)"
                )

    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AI-powered coaching assistant — manage clients, track stories, and deliver actionable coaching guidance.",
    lifespan=lifespan,
)

app.include_router(chat_router, prefix="/api", tags=["chat"])
app.include_router(ingest_router, prefix="/api", tags=["ingest"])
app.include_router(briefing_router, prefix="/api", tags=["briefing"])
app.include_router(users_router, prefix="/api", tags=["users"])
app.include_router(tools_router, prefix="/api", tags=["tools"])
app.include_router(openai_compat_router, tags=["openai-compat"])


@app.get("/health")
async def health_check():
    """Report the application status and LLM provider availability."""
    from app.core.model_registry import (
        LOCAL_MODEL_ID,
        openrouter_availability_reason,
        openrouter_models,
        probe_openrouter,
    )

    cloud_ok = await probe_openrouter()
    openrouter_info: dict = {
        "models": openrouter_models(),
        "available": cloud_ok,
    }
    if not cloud_ok:
        openrouter_info["reason"] = openrouter_availability_reason()

    from app.core.embeddings import probe_embed_model

    embed_available = probe_embed_model() if settings.tool_router_enabled else False
    embed_info = {
        "model": settings.ollama_embed_model,
        "available": embed_available,
        "backend": settings.tool_router_backend,
        "enabled": settings.tool_router_enabled,
    }

    rerank_info: dict = {
        "enabled": settings.rag_rerank_enabled,
        "model": settings.rag_rerank_model,
        "available": False,
    }
    if settings.rag_rerank_enabled:
        from app.rag.reranker import probe_rerank_model
        rerank_info["available"] = probe_rerank_model()

    return {
        "status": "ok",
        "default_model": LOCAL_MODEL_ID,
        "providers": {
            "ollama": {
                "model": settings.ollama_model,
                "available": True,
            },
            "openrouter": openrouter_info,
        },
        "embeddings": embed_info,
        "rerank": rerank_info,
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
