"""API request/response schemas."""

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
