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
3. Open WebUI forwarded headers (when ``ENABLE_FORWARD_USER_INFO_HEADERS=true``):
   ``X-OpenWebUI-User-Id`` and ``X-OpenWebUI-User-Name``
4. Defaults to ``"openwebui-user"`` if none of the above are provided.

Coach accounts are stored separately from client/patient records so the
logged-in coach does not appear in ``list_clients`` results.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import AsyncGenerator, Optional

from app.core.observability import bind_message, log_step, preview, reset_message

import httpx
from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.api.chat import build_system_prompt, session_manager, store
from app.core.config import settings
from app.core.llm import generate_response, try_direct_reply_with_meta
from app.core.model_registry import (
    LOCAL_MODEL_ID,
    is_cloud_model_id,
    list_available_models,
    probe_openrouter,
)
from app.core.tools import TOOL_DEFINITIONS

router = APIRouter()
logger = logging.getLogger(__name__)

_MODEL_ID = LOCAL_MODEL_ID
_LOCAL_LLM_UNAVAILABLE_MESSAGE = (
    "I'm temporarily unable to reach the language model. "
    "If you're running via Docker, ensure Ollama is running on your host and "
    "that OLLAMA_BASE_URL points to host.docker.internal (not localhost)."
)
_CLOUD_LLM_UNAVAILABLE_MESSAGE = (
    "I'm temporarily unable to reach the cloud language model via OpenRouter. "
    "Check that OPENROUTER_API_KEY is valid, try again in a moment, "
    "or switch to Coach Assistant AI (Local) for offline use."
)


def _llm_error_hint(exc: Exception, *, cloud: bool) -> Optional[str]:
    """Return a short, user-facing hint derived from the provider error."""
    if isinstance(exc, httpx.TimeoutException):
        if cloud:
            return (
                "request timed out — cloud models can be slow; "
                "try again or use the local model"
            )
        return "request timed out"
    if isinstance(exc, httpx.ConnectError):
        return "could not connect to OpenRouter" if cloud else "could not connect to Ollama"
    if isinstance(exc, httpx.HTTPStatusError):
        if cloud:
            try:
                body = exc.response.json()
                message = body.get("error", {}).get("message")
                if isinstance(message, str) and message.strip():
                    return message.strip()
            except (json.JSONDecodeError, ValueError, AttributeError):
                pass
            return f"OpenRouter returned HTTP {exc.response.status_code}"
        return f"Ollama returned HTTP {exc.response.status_code}"
    return None


def _llm_unavailable_message(model_id: str, exc: Optional[Exception] = None) -> str:
    """Return a provider-appropriate message when the LLM request fails."""
    cloud = is_cloud_model_id(model_id)
    base = _CLOUD_LLM_UNAVAILABLE_MESSAGE if cloud else _LOCAL_LLM_UNAVAILABLE_MESSAGE
    if exc is None:
        return base
    hint = _llm_error_hint(exc, cloud=cloud)
    return f"{base} ({hint})" if hint else base


async def _maybe_format_direct_reply(
    user_message: str,
    direct_reply: Optional[str],
    model_id: str,
    *,
    tool: str | None = None,
    hint: str | None = None,
) -> Optional[str]:
    """Apply the optional LLM formatter to a fast-path data reply.

    Returns *direct_reply* unchanged when the formatter is disabled, the reply
    is not a formattable data result, or formatting fails (the formatter itself
    falls back to the deterministic template internally).
    """
    if direct_reply is None:
        return None

    from app.core.model_registry import resolve_provider
    from app.core.response_formatter import format_data_reply, is_formattable

    if not is_formattable(direct_reply):
        logger.info("response_formatter: SKIP (not a formattable fast-path reply)")
        return direct_reply

    if not settings.response_formatter_enabled:
        logger.debug(
            "response_formatter: LLM pass skipped (RESPONSE_FORMATTER_ENABLED=false); "
            "deterministic table formatting still applies when requested"
        )

    provider = resolve_provider(model_id)
    return await format_data_reply(
        user_message, direct_reply, provider, tool=tool, hint=hint
    )


async def _generate_reply_or_unavailable(
    *,
    history: list[dict],
    system_prompt: str,
    model_id: str,
) -> str:
    try:
        return await generate_response(
            messages=history,
            system_prompt=system_prompt,
            tools=TOOL_DEFINITIONS,
            store=store,
            model_id=model_id,
        )
    except Exception as exc:
        logger.exception("LLM request failed during chat completion")
        return _llm_unavailable_message(model_id, exc)


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
        if self.model == LOCAL_MODEL_ID or is_cloud_model_id(self.model):
            return self.model
        return LOCAL_MODEL_ID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_user_id(
    request_user: Optional[str],
    header_user: Optional[str],
    openwebui_user_id: Optional[str],
) -> str:
    return request_user or header_user or openwebui_user_id or "openwebui-user"


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


async def _stream_text_reply(
    reply: str,
    session_id: str,
    completion_id: str,
    created: int,
) -> AsyncGenerator[str, None]:
    """Stream a precomputed reply in small chunks for Open WebUI."""
    chunk_size = 6
    for i in range(0, len(reply), chunk_size):
        yield _make_chunk(completion_id, created, content=reply[i : i + chunk_size])
        await asyncio.sleep(0)

    store.add_message(session_id, "assistant", reply)
    await session_manager.maybe_update_summary(
        session_id, threshold=settings.summary_trigger_messages
    )

    yield _make_chunk(completion_id, created, finish_reason="stop")
    yield "data: [DONE]\n\n"


async def _stream_and_persist(
    history: list[dict],
    system_prompt: str,
    session_id: str,
    completion_id: str,
    created: int,
    model_id: str = LOCAL_MODEL_ID,
    *,
    direct_reply: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """Tool-calling + optional streaming response, then persist the full reply."""
    if direct_reply is not None:
        async for chunk in _stream_text_reply(
            direct_reply, session_id, completion_id, created
        ):
            yield chunk
        return

    # Tool-calling is always resolved first (non-streaming) so the agentic loop
    # can execute multiple tool calls before producing a final answer.
    full_reply = await _generate_reply_or_unavailable(
        history=history,
        system_prompt=system_prompt,
        model_id=model_id,
    )

    async for chunk in _stream_text_reply(
        full_reply, session_id, completion_id, created
    ):
        yield chunk


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
    x_openwebui_user_id: Optional[str] = Header(
        default=None, alias="X-OpenWebUI-User-Id"
    ),
    x_openwebui_user_name: Optional[str] = Header(
        default=None, alias="X-OpenWebUI-User-Name"
    ),
):
    """OpenAI-compatible chat completion endpoint.

    Supports both streaming (``"stream": true``) and non-streaming responses.
    The latest user message is persisted in the coaching session and all
    coaching context (RAG, user profile, session summary) is injected into
    the system prompt automatically.
    """
    model_id = request.effective_model_id()

    # Reject cloud requests when OpenRouter is not available.
    if is_cloud_model_id(model_id) and not await probe_openrouter():
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

    user_id = _resolve_user_id(request.user, x_user_id, x_openwebui_user_id)
    coach_name = (x_openwebui_user_name or "").strip() or None

    msg_id = bind_message(user_id)
    t0 = time.monotonic()

    # Extract the latest user message for RAG retrieval and persistence.
    user_messages = [m for m in request.messages if m.role == "user"]
    last_user_message = user_messages[-1].content if user_messages else ""

    if settings.log_step_payloads:
        log_step(logger, "message", "received", endpoint="/v1/chat/completions",
                 stream=request.stream, model=model_id,
                 len=len(last_user_message), text=preview(last_user_message))
    else:
        log_step(logger, "message", "received", endpoint="/v1/chat/completions",
                 stream=request.stream, model=model_id, len=len(last_user_message))

    session_id = session_manager.get_or_create_session_id(
        user_id, coach_name=coach_name
    )
    if last_user_message:
        store.add_message(session_id, "user", last_user_message)

    history = store.get_session_messages(session_id)
    direct_meta = try_direct_reply_with_meta(last_user_message, store, history)
    direct_reply = await _maybe_format_direct_reply(
        last_user_message,
        direct_meta.reply if direct_meta is not None else None,
        model_id,
        tool=direct_meta.tool if direct_meta is not None else None,
        hint=direct_meta.hint if direct_meta is not None else None,
    )

    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())

    if request.stream:
        system_prompt = ""
        if direct_reply is None:
            system_prompt = await asyncio.to_thread(
                build_system_prompt, user_id, last_user_message
            )
        path = "direct" if direct_reply is not None else "llm"
        ms = int((time.monotonic() - t0) * 1000)
        log_step(logger, "message", "done", endpoint="/v1/chat/completions",
                 path=path, stream=True, ms=ms)
        reset_message()
        return StreamingResponse(
            _stream_and_persist(
                history,
                system_prompt,
                session_id,
                completion_id,
                created,
                model_id=model_id,
                direct_reply=direct_reply,
            ),
            media_type="text/event-stream",
        )

    if direct_reply is not None:
        reply = direct_reply
        path = "direct"
    else:
        system_prompt = await asyncio.to_thread(
            build_system_prompt, user_id, last_user_message
        )
        reply = await _generate_reply_or_unavailable(
            history=history,
            system_prompt=system_prompt,
            model_id=model_id,
        )
        path = "llm"
    store.add_message(session_id, "assistant", reply)
    await session_manager.maybe_update_summary(
        session_id, threshold=settings.summary_trigger_messages
    )

    ms = int((time.monotonic() - t0) * 1000)
    log_step(logger, "message", "done", endpoint="/v1/chat/completions",
             path=path, ms=ms)
    reset_message()

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
