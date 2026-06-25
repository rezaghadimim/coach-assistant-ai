"""Chat endpoint — POST /chat."""

import asyncio
import json
import logging
import time

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.core.llm import generate_response, try_direct_reply_with_meta
from app.core.observability import bind_message, log_step, preview, reset_message
from app.core.prompts import COACH_ASSISTANT_SYSTEM_PROMPT
from app.core.tools import TOOL_DEFINITIONS
from app.memory import MemoryStore, SessionManager
from app.models.schemas import ChatRequest, ChatResponse
from app.rag.retriever import format_coach_retrieval_context, retrieve_coach_context

router = APIRouter()
logger = logging.getLogger(__name__)

# Backward-compatible in-memory cache used by existing phase-1 tests.
_sessions: dict[str, list[dict[str, str]]] = {}

store = MemoryStore(settings.memory_db_path)
session_manager = SessionManager(store)


def reset_runtime_state() -> None:
    """Reset in-memory and persisted runtime state (for tests)."""
    _sessions.clear()
    session_manager.reset()
    store.clear_all_data()


def build_system_prompt(user_id: str, message: str) -> str:
    sections = [COACH_ASSISTANT_SYSTEM_PROMPT]

    if settings.rag_enabled:
        result = retrieve_coach_context(message)
        rag_context = format_coach_retrieval_context(result)
        if rag_context:
            sections.append(rag_context)

    user = store.get_user(user_id)
    if user and user.get("name"):
        sections.append(f"## Coach\nYou are assisting **{user['name']}**.")

    # Inject client notes/stories/decisions as documentation context
    client_notes = store.get_client_notes(user_id)
    if client_notes:
        notes_text = "## Client Documentation\n"
        for note in client_notes[:10]:  # Limit to 10 most recently updated notes
            note_header = f"**[{note['note_type'].upper()}]**"
            if note.get("title"):
                note_header += f" {note['title']}"
            note_header += f" ({note['updated_at']})"
            notes_text += f"- {note_header}: {note['content']}\n"
        sections.append(notes_text)

    last_summary = store.get_last_closed_summary(user_id)
    if last_summary:
        sections.append(f"## Previous Session Record\n{last_summary}")

    return "\n\n".join(sections)


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Handle a coaching chat message and persist user context."""
    msg_id = bind_message(request.user_id)
    t0 = time.monotonic()
    path = "unknown"
    try:
        if settings.log_step_payloads:
            log_step(logger, "message", "received", endpoint="/api/chat",
                     len=len(request.message), text=preview(request.message))
        else:
            log_step(logger, "message", "received", endpoint="/api/chat",
                     len=len(request.message))

        session_id = session_manager.get_or_create_session_id(request.user_id)
        store.add_message(session_id, "user", request.message)
        history = store.get_session_messages(session_id)
        _sessions[request.user_id] = history

        direct_meta = try_direct_reply_with_meta(request.message, store, history)
        if direct_meta is None:
            path = "llm"
            system_prompt = await asyncio.to_thread(
                build_system_prompt, request.user_id, request.message
            )
            reply = await generate_response(
                messages=history,
                system_prompt=system_prompt,
                tools=TOOL_DEFINITIONS,
                store=store,
            )
        else:
            path = "direct"
            reply = direct_meta.reply
            from app.core.model_registry import resolve_provider
            from app.core.response_formatter import format_data_reply, is_formattable
            if is_formattable(reply):
                provider = resolve_provider(None)
                reply = await format_data_reply(
                    request.message,
                    reply,
                    provider,
                    tool=direct_meta.tool,
                    hint=direct_meta.hint,
                )
        store.add_message(session_id, "assistant", reply)

        history = store.get_session_messages(session_id)
        _sessions[request.user_id] = history
        await session_manager.maybe_update_summary(
            session_id,
            threshold=settings.summary_trigger_messages,
        )
    except HTTPException:
        ms = int((time.monotonic() - t0) * 1000)
        log_step(logger, "message", "error", level=logging.ERROR,
                 endpoint="/api/chat", ms=ms, exc="HTTPException")
        raise
    except Exception as exc:
        ms = int((time.monotonic() - t0) * 1000)
        log_step(logger, "message", "error", level=logging.ERROR,
                 endpoint="/api/chat", ms=ms, exc=type(exc).__name__)
        raise HTTPException(
            status_code=502,
            detail=f"LLM service error: {exc}",
        ) from exc
    finally:
        ms = int((time.monotonic() - t0) * 1000)
        log_step(logger, "message", "done", endpoint="/api/chat",
                 path=path, ms=ms)
        reset_message()

    return ChatResponse(
        user_id=request.user_id,
        message=request.message,
        reply=reply,
    )
