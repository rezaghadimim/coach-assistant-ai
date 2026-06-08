"""Shared types for LLM provider abstraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncGenerator, Optional, Protocol


@dataclass
class ToolCall:
    """A single tool-call requested by the model."""

    id: str
    name: str
    arguments: dict


@dataclass
class CompletionResult:
    """Normalised response from any provider's chat-completion call."""

    # Filled when the model returned a text reply (no more tool calls).
    content: str = ""
    # Filled when the model requested tool calls.
    tool_calls: list[ToolCall] = field(default_factory=list)
    # Raw assistant message dict for appending to the conversation history.
    # Providers fill this so callers can push it back verbatim.
    assistant_message: dict = field(default_factory=dict)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class LLMProvider(Protocol):
    """Minimal interface any provider must satisfy."""

    async def complete(
        self,
        messages: list[dict],
        *,
        tools: Optional[list[dict]] = None,
    ) -> CompletionResult: ...

    async def stream(
        self,
        messages: list[dict],
    ) -> AsyncGenerator[str, None]: ...
