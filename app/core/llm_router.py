"""LLM router fallback — constrained single-call tool classifier.

Used as the final fast-path layer before falling into the full LLM tool-calling
loop. Makes one compact LLM completion that must return JSON
``{"tool": "<name>"}`` (or ``{"tool": "none"}``), then validates the result
against the known tool enum.

This catches arbitrary phrasings that the token/embedding/rerank layers miss
(open-ended natural language, rare vocabulary, multi-clause instructions) while
remaining faster than a full tool-calling loop because:
  - No tool schema is sent — just a short system + user prompt.
  - The model only needs to classify, not construct tool arguments.
  - Param extraction is delegated to existing deterministic helpers.

Gated by ``settings.tool_router_llm_fallback_enabled``.  Returns ``None`` on
any failure (network, malformed JSON, unknown tool) so callers always fall
through gracefully.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Optional

from app.core.config import settings

if TYPE_CHECKING:
    from app.core.tool_router import ToolMatch

logger = logging.getLogger(__name__)

# Canonical tool names the router may return.
_KNOWN_TOOLS = frozenset(
    {
        "create_client",
        "add_client_note",
        "update_client_note",
        "delete_client_note",
        "delete_client",
        "get_client",
        "get_client_full",
        "list_client_notes",
        "list_clients",
    }
)

_SYSTEM_PROMPT = """\
You are a tool classifier for a life-coaching assistant.
Given a coach message, decide which ONE tool name best matches — or "none".

Available tools:
- create_client: register a new client or update their profile (age, email, phone, occupation, background)
- add_client_note: save a note, goal, decision, story, or progress update for a client
- update_client_note: edit an existing note by note id
- delete_client_note: remove a note by note id
- delete_client: remove a client and all their data
- get_client: retrieve a client's profile/contact fields only
- get_client_full: retrieve everything about a client (profile + all notes)
- list_client_notes: list notes for a specific client, optionally filtered by type
- list_clients: show all registered clients

Respond with ONLY valid JSON and no extra text:
{"tool": "<tool_name_or_none>"}

Rules:
- Use "none" if the message is a general coaching question or does not map to any tool.
- Prefer specific tools over general ones when the intent is clear.

Examples:
- "give me all visitors in table" → {"tool": "list_clients"}
- "what is Ali's age?" → {"tool": "get_client"}
- "show me everything about Sara" → {"tool": "get_client_full"}
- "what are Ali's goals?" → {"tool": "list_client_notes"}
- "how can I help Ali feel less overwhelmed?" → {"tool": "none"}
- "what's a good question to ask about procrastination?" → {"tool": "none"}
- "in general how do I run a GROW session?" → {"tool": "none"}
- "I want to know one way to build trust with a new client" → {"tool": "none"}
"""

# JSON schema for constrained decoding via Ollama's format= parameter.
# Forces the model to emit exactly {"tool": "<one of the valid names>"}.
_ROUTER_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "tool": {
            "type": "string",
            "enum": [
                "create_client",
                "add_client_note",
                "update_client_note",
                "delete_client_note",
                "delete_client",
                "get_client",
                "get_client_full",
                "list_client_notes",
                "list_clients",
                "none",
            ],
        }
    },
    "required": ["tool"],
}


def _parse_tool_from_response(content: str) -> Optional[str]:
    """Extract and validate a tool name from the model's JSON response."""
    stripped = content.strip()
    # Accept bare JSON or JSON embedded in text.
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return None
    tool = data.get("tool", "").strip().lower()
    if tool == "none" or not tool:
        return None
    if tool not in _KNOWN_TOOLS:
        logger.debug("llm_router: model returned unknown tool %r — ignoring", tool)
        return None
    return tool


async def classify_tool_llm(
    message: str,
    *,
    provider=None,
) -> "Optional[ToolMatch]":
    """Classify *message* with a single constrained LLM call.

    Returns a :class:`~app.core.tool_router.ToolMatch` with
    ``backend="llm"`` when confident, or ``None`` to defer to the full loop.

    Failures (network, timeout, bad JSON, unknown tool) are caught and logged;
    the caller always receives ``None`` on any error.
    """
    if not settings.tool_router_llm_fallback_enabled:
        return None

    from app.core.tool_router import ToolMatch

    if provider is None:
        from app.core.llm_providers.ollama import OllamaProvider
        provider = OllamaProvider()

    messages = [{"role": "user", "content": message}]
    full_messages = [{"role": "system", "content": _SYSTEM_PROMPT}] + messages

    try:
        result = await provider.complete(
            full_messages,
            temperature=settings.temperature_tool,
            num_predict=settings.max_tokens_classify,
            format=_ROUTER_SCHEMA,
        )
        content = result.content if hasattr(result, "content") else str(result)
    except Exception as exc:
        logger.debug("llm_router: provider call failed: %s", exc)
        return None

    tool_name = _parse_tool_from_response(content)
    if tool_name is None:
        logger.debug("llm_router: no valid tool extracted from %r", content[:100])
        return None

    logger.debug("llm_router: classified message as tool=%s", tool_name)
    return ToolMatch(
        tool=tool_name,
        score=1.0,
        hint=None,
        utterance=None,
        backend="llm",
        rerank_score=None,
    )
