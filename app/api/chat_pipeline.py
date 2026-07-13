"""Shared chat turn orchestration for API endpoints."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.config import settings
from app.core.tools import TOOL_DEFINITIONS
from app.rag.expert_ideas import ExpertIdea, format_expert_ideas_markdown

if TYPE_CHECKING:
    from app.core.llm import DirectReplyMeta
    from app.memory import MemoryStore, SessionManager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatTurnResult:
    """Outcome of one persisted chat turn."""

    reply: str
    path: str
    ideas: list[ExpertIdea]
    session_id: str
    history: list[dict[str, str]]


async def _format_direct_reply(
    user_message: str,
    reply: str,
    *,
    tool: str | None,
    hint: str | None,
    model_id: str | None,
    gate_formatting_on_setting: bool,
) -> str:
    from app.core.model_registry import resolve_provider
    from app.core.response_formatter import format_data_reply, is_formattable

    if not is_formattable(reply):
        return reply

    if gate_formatting_on_setting and not settings.response_formatter_enabled:
        logger.debug(
            "response_formatter: LLM pass skipped (RESPONSE_FORMATTER_ENABLED=false); "
            "deterministic table formatting still applies when requested"
        )

    provider = resolve_provider(model_id)
    return await format_data_reply(
        user_message, reply, provider, tool=tool, hint=hint
    )


async def run_chat_turn(
    *,
    user_id: str,
    message: str,
    store: MemoryStore,
    session_manager: SessionManager,
    generate_response: Callable[..., Awaitable[str]],
    try_direct_reply_with_meta: Callable[..., DirectReplyMeta | None],
    build_prompt_and_ideas: Callable[..., tuple[str, list[ExpertIdea]]],
    on_history: Callable[[list[dict[str, str]]], None] | None = None,
    coach_name: str | None = None,
    model_id: str | None = None,
    gate_formatting_on_setting: bool = False,
    persist_user_message: bool = True,
    generate_reply_fn: Callable[..., Awaitable[str]] | None = None,
) -> ChatTurnResult:
    """Run persist→history→direct-reply→prompt→generate→persist→schedule-summary."""
    path = "unknown"
    session_id = session_manager.get_or_create_session_id(
        user_id, coach_name=coach_name
    )

    if persist_user_message and message:
        store.add_message(session_id, "user", message)

    history = store.get_session_messages(session_id)
    if on_history is not None:
        on_history(history)

    ideas: list[ExpertIdea] = []
    direct_meta = try_direct_reply_with_meta(message, store, history)
    if direct_meta is None:
        path = "llm"
        system_prompt, ideas = await asyncio.to_thread(
            build_prompt_and_ideas, user_id, message
        )
        if generate_reply_fn is not None:
            reply = await generate_reply_fn(
                history=history,
                system_prompt=system_prompt,
            )
        else:
            gen_kwargs: dict = {
                "messages": history,
                "system_prompt": system_prompt,
                "tools": TOOL_DEFINITIONS,
                "store": store,
                "skip_direct_reply": True,
            }
            if model_id is not None:
                gen_kwargs["model_id"] = model_id
            reply = await generate_response(**gen_kwargs)
        ideas_section = format_expert_ideas_markdown(ideas)
        if ideas_section:
            reply = f"{reply}\n\n{ideas_section}"
    else:
        path = "direct"
        reply = await _format_direct_reply(
            message,
            direct_meta.reply,
            tool=direct_meta.tool,
            hint=direct_meta.hint,
            model_id=model_id,
            gate_formatting_on_setting=gate_formatting_on_setting,
        )

    store.add_message(session_id, "assistant", reply)
    history = store.get_session_messages(session_id)
    if on_history is not None:
        on_history(history)
    session_manager.schedule_update_summary(
        session_id,
        threshold=settings.summary_trigger_messages,
    )
    return ChatTurnResult(
        reply=reply,
        path=path,
        ideas=ideas,
        session_id=session_id,
        history=history,
    )
