"""Chat endpoint — POST /chat."""

from fastapi import APIRouter, HTTPException

from app.core.llm import generate_response
from app.models.schemas import ChatRequest, ChatResponse

router = APIRouter()

# Simple in-memory session store (Phase 1 only; replaced by DB in Phase 3)
_sessions: dict[str, list[dict[str, str]]] = {}


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Handle a coaching chat message.

    Maintains per-user message history in memory and sends the full
    conversation context to the LLM for response generation.
    """
    # Get or create session history
    history = _sessions.setdefault(request.user_id, [])

    # Append user message
    history.append({"role": "user", "content": request.message})

    try:
        reply = await generate_response(messages=history)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"LLM service error: {exc}",
        ) from exc

    # Append assistant reply to history
    history.append({"role": "assistant", "content": reply})

    return ChatResponse(
        user_id=request.user_id,
        message=request.message,
        reply=reply,
    )
