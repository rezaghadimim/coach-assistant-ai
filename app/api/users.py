"""User and session management endpoints."""

from fastapi import APIRouter, HTTPException

from app.api.chat import session_manager, store
from app.models.schemas import (
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
    session_id = session_manager.start_new_session(user_id)
    return NewSessionResponse(user_id=user_id, session_id=session_id)
