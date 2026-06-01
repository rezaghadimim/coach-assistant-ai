"""Life Coach AI — Application entry point."""

import uvicorn
from fastapi import FastAPI

from app.api.chat import router as chat_router
from app.core.config import settings

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AI-powered life coaching assistant using local LLMs.",
)

app.include_router(chat_router, prefix="/api", tags=["chat"])


@app.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {"status": "ok", "model": settings.ollama_model}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
