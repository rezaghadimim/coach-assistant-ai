"""Chat endpoint — POST /chat."""

import asyncio
import json

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.core.llm import generate_response, try_direct_reply
from app.core.prompts import COACH_ASSISTANT_SYSTEM_PROMPT
from app.core.tools import TOOL_DEFINITIONS
from app.memory import MemoryStore, SessionManager
from app.models.schemas import ChatRequest, ChatResponse
from app.rag.retriever import format_retrieval_context, retrieve

router = APIRouter()

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
        from app.rag.retriever import Backend
        context_chunks = retrieve(
            message,
            top_k=settings.rag_top_k,
            min_score=settings.rag_min_score,
            backend=settings.rag_backend,  # type: ignore[arg-type]
        )
        rag_context = format_retrieval_context(context_chunks)
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
    try:
        session_id = session_manager.get_or_create_session_id(request.user_id)
        store.add_message(session_id, "user", request.message)
        history = store.get_session_messages(session_id)
        _sessions[request.user_id] = history

        reply = try_direct_reply(request.message, store, history)
        if reply is None:
            system_prompt = await asyncio.to_thread(
                build_system_prompt, request.user_id, request.message
            )
            reply = await generate_response(
                messages=history,
                system_prompt=system_prompt,
                tools=TOOL_DEFINITIONS,
                store=store,
            )
        elif settings.response_formatter_enabled:
            from app.core.model_registry import resolve_provider
            from app.core.response_formatter import format_data_reply, is_formattable
            if is_formattable(reply):
                provider = resolve_provider(None)
                reply = await format_data_reply(request.message, reply, provider)
        store.add_message(session_id, "assistant", reply)

        history = store.get_session_messages(session_id)
        _sessions[request.user_id] = history
        await session_manager.maybe_update_summary(
            session_id,
            threshold=settings.summary_trigger_messages,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"LLM service error: {exc}",
        ) from exc

    return ChatResponse(
        user_id=request.user_id,
        message=request.message,
        reply=reply,
    )
