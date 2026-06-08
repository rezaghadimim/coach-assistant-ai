"""OpenAI-compatible API endpoints for Open WebUI integration.

Exposes /v1/models and /v1/chat/completions so that Open WebUI (or any
OpenAI-API-compatible client) can connect to this Coach Assistant AI backend
while still using all coaching features: RAG context, SQLite memory, client
notes, and session summaries.

User identification
-------------------
The coaching session is keyed on a *user_id*.  Callers can supply it via:

1. The ``user`` field in the request body  (``{"user": "alice", ...}``)
2. The ``X-User-Id`` HTTP request header
3. Defaults to ``"openwebui-user"`` if neither is provided.
"""

import asyncio
import json
import logging
import time
import uuid
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.api.chat import build_system_prompt, session_manager, store
from app.core.config import settings
from app.core.llm import generate_response
from app.core.model_registry import (
    CLOUD_MODEL_ID,
    LOCAL_MODEL_ID,
    list_available_models,
    probe_openrouter,
)
from app.core.tools import TOOL_DEFINITIONS

router = APIRouter()
logger = logging.getLogger(__name__)

_MODEL_ID = LOCAL_MODEL_ID
_LLM_UNAVAILABLE_MESSAGE = (
    "I'm temporarily unable to reach the language model. "
    "If you're running via Docker, ensure Ollama is running on your host and "
    "that OLLAMA_BASE_URL points to host.docker.internal (not localhost)."
)


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class _OpenAIMessage(BaseModel):
    role: str
    content: str


class _ChatCompletionRequest(BaseModel):
    model: str = _MODEL_ID
    messages: list[_OpenAIMessage]
    stream: bool = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    user: Optional[str] = None

    def effective_model_id(self) -> str:
        """Normalise the requested model ID, defaulting unknown IDs to local."""
        if self.model in (LOCAL_MODEL_ID, CLOUD_MODEL_ID):
            return self.model
        return LOCAL_MODEL_ID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_user_id(
    request_user: Optional[str],
    header_user: Optional[str],
) -> str:
    return request_user or header_user or "openwebui-user"


def _make_chunk(
    completion_id: str,
    created: int,
    *,
    content: Optional[str] = None,
    finish_reason: Optional[str] = None,
) -> str:
    delta = {"content": content} if content is not None else {}
    chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": _MODEL_ID,
        "choices": [
            {
                "delta": delta,
                "index": 0,
                "finish_reason": finish_reason,
            }
        ],
    }
    return f"data: {json.dumps(chunk)}\n\n"


async def _stream_and_persist(
    history: list[dict],
    system_prompt: str,
    session_id: str,
    completion_id: str,
    created: int,
    model_id: str = LOCAL_MODEL_ID,
) -> AsyncGenerator[str, None]:
    """Tool-calling + optional streaming response, then persist the full reply."""
    # Tool-calling is always resolved first (non-streaming) so the agentic loop
    # can execute multiple tool calls before producing a final answer.
    try:
        full_reply = await generate_response(
            messages=history,
            system_prompt=system_prompt,
            tools=TOOL_DEFINITIONS,
            store=store,
            model_id=model_id,
        )
    except Exception:
        logger.exception("LLM request failed during streaming chat completion")
        full_reply = _LLM_UNAVAILABLE_MESSAGE

    # Stream the final reply in small chunks so Open WebUI shows progressive output.
    chunk_size = 6
    for i in range(0, len(full_reply), chunk_size):
        yield _make_chunk(completion_id, created, content=full_reply[i : i + chunk_size])
        await asyncio.sleep(0)

    store.add_message(session_id, "assistant", full_reply)
    session_manager.maybe_update_summary(
        session_id, threshold=settings.summary_trigger_messages
    )

    yield _make_chunk(completion_id, created, finish_reason="stop")
    yield "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/v1/models")
async def list_models():
    """Return available coaching models.

    Always includes the local Ollama model. The cloud OpenRouter model is
    included only when OPENROUTER_API_KEY is set and the availability probe
    passes (checked with a 60-second cache).
    """
    models = await list_available_models()
    return {"object": "list", "data": models}


@router.post("/v1/chat/completions")
async def chat_completions(
    request: _ChatCompletionRequest,
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
):
    """OpenAI-compatible chat completion endpoint.

    Supports both streaming (``"stream": true``) and non-streaming responses.
    The latest user message is persisted in the coaching session and all
    coaching context (RAG, user profile, session summary) is injected into
    the system prompt automatically.
    """
    model_id = request.effective_model_id()

    # Reject cloud requests when OpenRouter is not available.
    if model_id == CLOUD_MODEL_ID and not await probe_openrouter():
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "message": (
                        "Cloud model unavailable — check OPENROUTER_API_KEY "
                        "or use model 'coach-assistant-ai' for the local provider."
                    ),
                    "type": "service_unavailable",
                    "code": "cloud_model_unavailable",
                }
            },
        )

    user_id = _resolve_user_id(request.user, x_user_id)

    # Extract the latest user message for RAG retrieval and persistence.
    user_messages = [m for m in request.messages if m.role == "user"]
    last_user_message = user_messages[-1].content if user_messages else ""

    session_id = session_manager.get_or_create_session_id(user_id)
    if last_user_message:
        store.add_message(session_id, "user", last_user_message)

    history = store.get_session_messages(session_id)
    system_prompt = build_system_prompt(user_id, last_user_message)

    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())

    if request.stream:
        return StreamingResponse(
            _stream_and_persist(
                history, system_prompt, session_id, completion_id, created,
                model_id=model_id,
            ),
            media_type="text/event-stream",
        )

    reply = await generate_response(
        messages=history,
        system_prompt=system_prompt,
        tools=TOOL_DEFINITIONS,
        store=store,
        model_id=model_id,
    )
    store.add_message(session_id, "assistant", reply)
    session_manager.maybe_update_summary(
        session_id, threshold=settings.summary_trigger_messages
    )

    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": model_id,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": reply},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": -1,
            "completion_tokens": -1,
            "total_tokens": -1,
        },
    }
