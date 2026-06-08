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
import time
import uuid
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.chat import build_system_prompt, session_manager, store
from app.core.config import settings
from app.core.llm import generate_response
from app.core.tools import TOOL_DEFINITIONS

router = APIRouter()

_MODEL_ID = "coach-assistant-ai"


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
) -> AsyncGenerator[str, None]:
    """Tool-calling + optional streaming response, then persist the full reply."""
    # Tool-calling is always resolved first (non-streaming) so the agentic loop
    # can execute multiple tool calls before producing a final answer.
    full_reply = await generate_response(
        messages=history,
        system_prompt=system_prompt,
        tools=TOOL_DEFINITIONS,
        store=store,
    )

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
    """Return the single coach-assistant-ai model entry."""
    return {
        "object": "list",
        "data": [
            {
                "id": _MODEL_ID,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "coach-assistant-ai",
            }
        ],
    }


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
                history, system_prompt, session_id, completion_id, created
            ),
            media_type="text/event-stream",
        )

    reply = await generate_response(
        messages=history,
        system_prompt=system_prompt,
        tools=TOOL_DEFINITIONS,
        store=store,
    )
    store.add_message(session_id, "assistant", reply)
    session_manager.maybe_update_summary(
        session_id, threshold=settings.summary_trigger_messages
    )

    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": _MODEL_ID,
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
