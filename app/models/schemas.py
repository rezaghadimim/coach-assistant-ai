"""API request/response schemas."""

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Incoming chat request payload."""

    user_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)


class ChatResponse(BaseModel):
    """Outgoing chat response payload."""

    user_id: str
    message: str
    reply: str


class IngestRequest(BaseModel):
    """Request payload for ingesting from configured document directory."""

    chunk_size: int | None = Field(default=None, gt=0)
    chunk_overlap: int | None = Field(default=None, ge=0)


class IngestResponse(BaseModel):
    """Ingest endpoint response payload."""

    docs_dir: str
    documents_indexed: int
    chunks_indexed: int


class UserCreateRequest(BaseModel):
    """Payload for creating or updating a user."""

    user_id: str = Field(..., min_length=1)
    name: str | None = None
    profile: dict[str, Any] = Field(default_factory=dict)


class UserResponse(BaseModel):
    """User profile response."""

    user_id: str
    name: str | None
    profile: dict[str, Any]


class SessionSummary(BaseModel):
    """Summary metadata for one coaching session."""

    session_id: str
    user_id: str
    started_at: str
    ended_at: str | None
    summary: str | None


class SessionListResponse(BaseModel):
    """Response payload for listing user sessions."""

    user_id: str
    sessions: list[SessionSummary]


class NewSessionResponse(BaseModel):
    """Response payload for explicitly starting a new session."""

    user_id: str
    session_id: str
