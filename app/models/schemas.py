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


# ------------------------------------------------------------------
# Case briefing (structured coach analysis)
# ------------------------------------------------------------------


class BriefingRequest(BaseModel):
    """Request payload for generating a structured coaching case briefing."""

    user_id: str = Field(..., min_length=1, description="Coach's user ID.")
    client_id: Optional[str] = Field(
        default=None,
        description="Client user_id to load notes and profile from the store. Optional.",
    )
    question: str = Field(
        ...,
        min_length=1,
        description="The coach's question or situation description to analyse.",
    )


class CoachBriefing(BaseModel):
    """Structured coaching case briefing returned by POST /api/briefing."""

    key_insights: list[str] = Field(
        default_factory=list,
        description="Key observations about the client's situation.",
    )
    hypotheses: list[str] = Field(
        default_factory=list,
        description="Tentative, non-clinical interpretations of underlying dynamics.",
    )
    coaching_questions: list[str] = Field(
        default_factory=list,
        description="Suggested powerful questions the coach could explore in session.",
    )
    recommended_framework: str = Field(
        default="",
        description="Suggested coaching framework (e.g. GROW, MI, CBT-informed, Solution-focused).",
    )
    framework_rationale: str = Field(
        default="",
        description="Brief explanation of why this framework fits the situation.",
    )
    action_plan: list[str] = Field(
        default_factory=list,
        description="Suggested session agenda or next-step structure for the coach.",
    )
    homework: list[str] = Field(
        default_factory=list,
        description="Between-session exercises or reflections to suggest to the client.",
    )


# ------------------------------------------------------------------
# Tool routing
# ------------------------------------------------------------------


class ToolClassifyRequest(BaseModel):
    """Request payload for classifying a message into a tool."""

    message: str = Field(..., min_length=1)


class ToolMatchItem(BaseModel):
    """A single tool candidate with its score."""

    tool: str
    score: float
    hint: Optional[str] = None
    utterance: Optional[str] = None


class ToolClassifyResponse(BaseModel):
    """Response from the tool classification endpoint."""

    message: str
    tool: Optional[str] = None
    score: Optional[float] = None
    hint: Optional[str] = None
    backend: Optional[str] = None
    top_n: list[ToolMatchItem] = Field(default_factory=list)
    deferred: bool = False


class ToolReindexResponse(BaseModel):
    """Response from the tool router reindex endpoint."""

    examples_indexed: int
    backend: str
