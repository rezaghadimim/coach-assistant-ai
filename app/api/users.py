"""User, session, and client-notes management endpoints."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.api.chat import session_manager, store
from app.models.schemas import (
    ClientNoteCreate,
    ClientNoteListResponse,
    ClientNoteResponse,
    ClientNoteUpdate,
    NewSessionResponse,
    SessionListResponse,
    SessionSummary,
    UserCreateRequest,
    UserResponse,
)

router = APIRouter()


@router.post("/users", response_model=UserResponse)
async def create_or_update_user(request: UserCreateRequest) -> UserResponse:
    """Create or update a user profile."""
    store.upsert_user(request.user_id, name=request.name, profile=request.profile)
    user = store.get_user(request.user_id)
    if user is None:
        raise HTTPException(status_code=500, detail="Failed to save user profile")
    return UserResponse(**user)


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: str) -> UserResponse:
    """Get one user profile."""
    user = store.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(**user)


@router.get("/sessions/{user_id}", response_model=SessionListResponse)
async def list_user_sessions(user_id: str) -> SessionListResponse:
    """List stored sessions for a user."""
    sessions = [SessionSummary(**session) for session in store.list_sessions(user_id)]
    return SessionListResponse(user_id=user_id, sessions=sessions)


@router.post("/sessions/{user_id}/new", response_model=NewSessionResponse)
async def start_new_session(user_id: str) -> NewSessionResponse:
    """Close previous session (with summary) and start a fresh one."""
    session_id = await session_manager.start_new_session(user_id)
    return NewSessionResponse(user_id=user_id, session_id=session_id)


# ------------------------------------------------------------------
# Client notes — per-client documentation, stories, decisions
# ------------------------------------------------------------------


@router.post("/clients/{user_id}/notes", response_model=ClientNoteResponse)
async def create_client_note(
    user_id: str, request: ClientNoteCreate
) -> ClientNoteResponse:
    """Add a note (story, decision, progress, etc.) to a client's file."""
    user = store.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Client not found")

    note_id = store.add_client_note(
        user_id,
        request.content,
        note_type=request.note_type,
        title=request.title,
        session_id=request.session_id,
    )
    notes = store.get_client_notes(user_id)
    note = next((n for n in notes if n["id"] == note_id), None)
    if note is None:
        raise HTTPException(status_code=500, detail="Failed to save note")
    return ClientNoteResponse(**note)


@router.get("/clients/{user_id}/notes", response_model=ClientNoteListResponse)
async def list_client_notes(
    user_id: str,
    note_type: Optional[str] = Query(default=None),
) -> ClientNoteListResponse:
    """List all notes for a client, optionally filtered by type."""
    notes = store.get_client_notes(user_id, note_type=note_type)
    return ClientNoteListResponse(
        user_id=user_id,
        notes=[ClientNoteResponse(**n) for n in notes],
    )


@router.put("/clients/{user_id}/notes/{note_id}", response_model=ClientNoteResponse)
async def update_client_note(
    user_id: str, note_id: int, request: ClientNoteUpdate
) -> ClientNoteResponse:
    """Update an existing client note (e.g. add a decision update)."""
    ok = store.update_client_note(
        note_id,
        request.content,
        title=request.title,
        note_type=request.note_type,
        user_id=user_id,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Note not found")
    notes = store.get_client_notes(user_id)
    note = next((n for n in notes if n["id"] == note_id), None)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return ClientNoteResponse(**note)


@router.delete("/clients/{user_id}/notes/{note_id}")
async def delete_client_note(user_id: str, note_id: int):
    """Delete a client note."""
    ok = store.delete_client_note(note_id, user_id=user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Note not found")
    return {"detail": "Note deleted"}
