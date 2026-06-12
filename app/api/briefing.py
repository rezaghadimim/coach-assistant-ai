"""Structured coaching case briefing endpoint — POST /api/briefing.

Returns a CoachBriefing JSON object for the coach to use in session preparation.
This is a separate, opt-in endpoint that does NOT affect the prose chat flow.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.core.llm_providers.ollama import OllamaProvider
from app.core.prompts import BRIEFING_PROMPT
from app.memory.store import MemoryStore
from app.models.schemas import BriefingRequest, CoachBriefing
from app.rag.retriever import format_retrieval_context, retrieve

logger = logging.getLogger(__name__)

router = APIRouter()

# Reuse the same MemoryStore instance as the chat module.
from app.api.chat import store as _store


def _build_briefing_context(request: BriefingRequest, store: MemoryStore) -> str:
    """Assemble context from client notes and RAG for the briefing prompt."""
    sections: list[str] = []

    # RAG knowledge context
    if settings.rag_enabled:
        chunks = retrieve(
            request.question,
            top_k=settings.rag_top_k,
            min_score=settings.rag_min_score,
            backend=settings.rag_backend,  # type: ignore[arg-type]
        )
        rag_context = format_retrieval_context(chunks)
        if rag_context:
            sections.append(rag_context)

    # Client notes (if client_id provided)
    if request.client_id:
        client_notes = store.get_client_notes(request.client_id)
        if client_notes:
            notes_text = "## Client Documentation\n"
            for note in client_notes[:15]:
                note_header = f"**[{note['note_type'].upper()}]**"
                if note.get("title"):
                    note_header += f" {note['title']}"
                note_header += f" ({note['updated_at']})"
                notes_text += f"- {note_header}: {note['content']}\n"
            sections.append(notes_text)

    sections.append(f"## Coach's Question\n{request.question}")
    return "\n\n".join(sections)


@router.post("/briefing", response_model=CoachBriefing)
async def generate_briefing(request: BriefingRequest) -> CoachBriefing:
    """Generate a structured coaching case briefing for the coach.

    Loads client notes (when client_id is provided) and relevant RAG context,
    then calls the LLM with BRIEFING_PROMPT to produce a structured JSON
    briefing — key insights, hypotheses, coaching questions, framework
    recommendation, action plan, and homework suggestions.
    """
    context = _build_briefing_context(request, _store)

    llm_messages = [
        {"role": "system", "content": BRIEFING_PROMPT},
        {"role": "user", "content": context},
    ]

    try:
        provider = OllamaProvider()
        result = await provider.complete(llm_messages)
        raw = result.content.strip()

        # Strip markdown code fences if the model wraps JSON in them.
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(
                line for line in lines
                if not line.startswith("```")
            ).strip()

        data = json.loads(raw)
        briefing = CoachBriefing(**data)
        logger.info(
            "briefing: generated for user=%s client=%s framework=%s",
            request.user_id,
            request.client_id,
            briefing.recommended_framework,
        )
        return briefing

    except json.JSONDecodeError as exc:
        logger.error("briefing: LLM returned invalid JSON: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="LLM returned a non-JSON response. Try again or simplify the question.",
        ) from exc
    except Exception as exc:
        logger.exception("briefing: unexpected error: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=f"LLM service error: {exc}",
        ) from exc
