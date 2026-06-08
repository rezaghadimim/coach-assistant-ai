"""Coach Assistant AI — Application entry point."""

import uvicorn
from fastapi import FastAPI

from app.api.chat import router as chat_router
from app.api.ingest import router as ingest_router
from app.api.openai_compat import router as openai_compat_router
from app.api.users import router as users_router
from app.core.config import settings

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AI-powered coaching assistant — manage clients, track stories, and deliver actionable coaching guidance.",
)

app.include_router(chat_router, prefix="/api", tags=["chat"])
app.include_router(ingest_router, prefix="/api", tags=["ingest"])
app.include_router(users_router, prefix="/api", tags=["users"])
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
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
