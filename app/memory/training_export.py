"""Export persisted coaching sessions as JSONL for LoRA fine-tuning."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from app.core.prompts import COACH_ASSISTANT_SYSTEM_PROMPT
from app.memory.store import MemoryStore

_EXPORT_ROLES = frozenset({"user", "assistant"})


@dataclass(frozen=True)
class ExportStats:
    sessions_scanned: int
    sessions_exported: int
    examples_written: int


def count_coaching_turns(messages: list[dict[str, str]]) -> int:
    """Count consecutive user→assistant pairs in a message list."""
    turns = 0
    index = 0
    while index < len(messages) - 1:
        if messages[index]["role"] == "user" and messages[index + 1]["role"] == "assistant":
            turns += 1
            index += 2
            continue
        index += 1
    return turns


def session_to_training_record(
    messages: list[dict[str, str]],
    *,
    system_prompt: str = COACH_ASSISTANT_SYSTEM_PROMPT,
    min_turns: int = 1,
) -> Optional[dict[str, Any]]:
    """Convert one session's messages into a fine-tuning record, or skip it."""
    coaching_messages = [
        {"role": message["role"], "content": message["content"].strip()}
        for message in messages
        if message["role"] in _EXPORT_ROLES and message["content"].strip()
    ]
    if count_coaching_turns(coaching_messages) < min_turns:
        return None

    return {
        "messages": [
            {"role": "system", "content": system_prompt},
            *coaching_messages,
        ]
    }


def export_training_data(
    store: MemoryStore,
    output_path: str | Path,
    *,
    min_turns: int = 4,
    ended_only: bool = True,
    system_prompt: str = COACH_ASSISTANT_SYSTEM_PROMPT,
) -> ExportStats:
    """Write coaching sessions from SQLite to a JSONL training file."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    sessions = store.list_all_sessions(ended_only=ended_only)
    examples_written = 0

    with path.open("w", encoding="utf-8") as handle:
        for session in sessions:
            messages = store.get_session_messages(session["session_id"])
            record = session_to_training_record(
                messages,
                system_prompt=system_prompt,
                min_turns=min_turns,
            )
            if record is None:
                continue
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            examples_written += 1

    return ExportStats(
        sessions_scanned=len(sessions),
        sessions_exported=examples_written,
        examples_written=examples_written,
    )
