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
from app.core.observability import log_step

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
Given a coach message, decide which ONE tool best fits — or "none".

Every tool reads or changes the stored records of a SPECIFIC client. Choose a
tool ONLY when the coach wants to look up, create, or modify the saved data of a
particular client (named, e.g. "Ali", or clearly referenced such as "my roster").

Available tools:
- create_client: register a new client or update their profile (age, email, phone, occupation, background)
- add_client_note: save a note, goal, decision, story, or progress update for a client
- update_client_note: edit an existing note by note id
- delete_client_note: remove a note by note id
- delete_client: remove a client and all their data
- get_client: retrieve a client's profile/contact fields only
- get_client_full: retrieve everything stored about a client (profile + all notes)
- list_client_notes: list the notes already saved for a specific client
- list_clients: show all registered clients

Respond with ONLY valid JSON and no extra text:
{"tool": "<tool_name_or_none>"}

Rules:
- Choose "none" for any request for coaching advice, ideas, examples, techniques,
  or suggestions — EVEN when it mentions goals, notes, progress, stories, or
  "a client". These ask for your expertise, not for data already on file.
- A tool applies only to a specific client's existing records ("Ali's goals",
  "Sara's profile", "everyone on my roster"). Generic or hypothetical phrasing
  ("a new client", "someone who...", "any client") means "none".
- "What/how should I ask, take, share, or do?" is coaching advice → "none".
  "What is on file for X?" or "list X's notes" is a tool.
- When unsure, choose "none".

Examples:
- "give me all visitors in a table" → {"tool": "list_clients"}
- "what is Ali's age?" → {"tool": "get_client"}
- "show me everything about Sara" → {"tool": "get_client_full"}
- "what are Ali's goals?" → {"tool": "list_client_notes"}
- "note that Reza finished the leadership course" → {"tool": "add_client_note"}
- "remove note 4 from Ali's record" → {"tool": "delete_client_note"}
- "how can I help Ali feel less overwhelmed?" → {"tool": "none"}
- "what's a good first goal to set with someone who feels stuck?" → {"tool": "none"}
- "what kind of notes are worth taking in a first meeting?" → {"tool": "none"}
- "what does meaningful progress look like for a perfectionist?" → {"tool": "none"}
- "share an analogy I can use with a client who fears failure" → {"tool": "none"}
- "what should I find out about a client in our first conversation?" → {"tool": "none"}
- "in general, how do I run a GROW session?" → {"tool": "none"}
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
        log_step(logger, "llm_router", "fail", level=logging.WARNING,
                 exc=type(exc).__name__)
        return None

    tool_name = _parse_tool_from_response(content)
    if tool_name is None:
        log_step(logger, "llm_router", "miss", level=logging.DEBUG,
                 raw=content[:60])
        return None

    log_step(logger, "llm_router", "hit", tool=tool_name)
    return ToolMatch(
        tool=tool_name,
        score=1.0,
        hint=None,
        utterance=None,
        backend="llm",
        rerank_score=None,
    )
