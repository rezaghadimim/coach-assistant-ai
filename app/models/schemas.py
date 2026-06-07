"""API request/response schemas."""

from typing import Any, Optional

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

    chunk_size: Optional[int] = Field(default=None, gt=0)
    chunk_overlap: Optional[int] = Field(default=None, ge=0)


class IngestResponse(BaseModel):
    """Ingest endpoint response payload."""

    docs_dir: str
    documents_indexed: int
    chunks_indexed: int


class UserCreateRequest(BaseModel):
    """Payload for creating or updating a user."""

    user_id: str = Field(..., min_length=1)
    name: Optional[str] = None
    profile: dict[str, Any] = Field(default_factory=dict)


class UserResponse(BaseModel):
    """User profile response."""

    user_id: str
    name: Optional[str]
    profile: dict[str, Any]


class SessionSummary(BaseModel):
    """Summary metadata for one coaching session."""

    session_id: str
    user_id: str
    started_at: str
    ended_at: Optional[str]
    summary: Optional[str]


class SessionListResponse(BaseModel):
    """Response payload for listing user sessions."""

    user_id: str
    sessions: list[SessionSummary]


class NewSessionResponse(BaseModel):
    """Response payload for explicitly starting a new session."""

    user_id: str
    session_id: str


# ------------------------------------------------------------------
# Client notes (per-client documentation, stories, decisions)
# ------------------------------------------------------------------


class ClientNoteCreate(BaseModel):
    """Payload for creating a note about a client."""

    user_id: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    note_type: str = Field(
        default="general",
        description="Type of note: general, story, decision, goal, progress",
    )
    title: Optional[str] = None
    session_id: Optional[str] = None


class ClientNoteUpdate(BaseModel):
    """Payload for updating an existing client note."""

    content: str = Field(..., min_length=1)
    title: Optional[str] = None
    note_type: Optional[str] = None


class ClientNoteResponse(BaseModel):
    """Single client note response."""

    id: int
    user_id: str
    session_id: Optional[str]
    note_type: str
    title: Optional[str]
    content: str
    created_at: str
    updated_at: str


class ClientNoteListResponse(BaseModel):
    """Response payload for listing client notes."""

    user_id: str
    notes: list[ClientNoteResponse]
