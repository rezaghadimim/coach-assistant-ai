"""In-memory observability for deferred tool-router classifications."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING, Any

from app.core.config import settings
from app.core.observability import preview

if TYPE_CHECKING:
    from app.core.tool_router import ToolMatch

_MAX_RECENT = 50
_MAX_HEALTH_RECENT = 5


@dataclass(frozen=True)
class RoutingDeferral:
    """One deferred classification captured for tuning."""

    message_preview: str
    backend: str
    top_tools: list[dict[str, Any]]
    near_miss: bool
    ts: float


_lock = Lock()
_deferrals_total = 0
_near_misses_total = 0
_recent: deque[RoutingDeferral] = deque(maxlen=_MAX_RECENT)


def _top_score(candidates: list["ToolMatch"]) -> float:
    if not candidates:
        return 0.0
    top = candidates[0]
    return top.rerank_score if top.rerank_score is not None else top.score


def _serialize_candidates(candidates: list["ToolMatch"]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for match in candidates[:3]:
        row: dict[str, Any] = {
            "tool": match.tool,
            "score": round(match.score, 4),
        }
        if match.rerank_score is not None:
            row["rerank_score"] = round(match.rerank_score, 4)
        if match.hint:
            row["hint"] = match.hint
        rows.append(row)
    return rows


def record_deferral(
    message: str,
    candidates: list["ToolMatch"],
    backend: str,
) -> RoutingDeferral:
    """Store a deferred routing attempt and return the recorded entry."""
    global _deferrals_total, _near_misses_total

    top_score = _top_score(candidates)
    near_miss = top_score >= settings.tool_router_near_miss_score
    entry = RoutingDeferral(
        message_preview=preview(message, 120),
        backend=backend,
        top_tools=_serialize_candidates(candidates),
        near_miss=near_miss,
        ts=time.time(),
    )

    with _lock:
        _deferrals_total += 1
        if near_miss:
            _near_misses_total += 1
        _recent.append(entry)

    return entry


def get_stats() -> dict[str, Any]:
    """Return aggregate deferral stats for health/debug surfaces."""
    with _lock:
        recent_near_misses = [
            {
                "message": item.message_preview,
                "backend": item.backend,
                "top_tools": item.top_tools,
                "top_score": (
                    item.top_tools[0].get("rerank_score")
                    or item.top_tools[0].get("score")
                    if item.top_tools
                    else 0.0
                ),
                "ts": item.ts,
            }
            for item in reversed(_recent)
            if item.near_miss
        ][: _MAX_HEALTH_RECENT]

        return {
            "deferrals_total": _deferrals_total,
            "near_misses_total": _near_misses_total,
            "near_miss_threshold": settings.tool_router_near_miss_score,
            "recent_near_misses": recent_near_misses,
        }


def reset_stats() -> None:
    """Clear counters and recent deferrals (for tests)."""
    global _deferrals_total, _near_misses_total

    with _lock:
        _deferrals_total = 0
        _near_misses_total = 0
        _recent.clear()
