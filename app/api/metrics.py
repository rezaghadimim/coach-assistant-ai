"""Prometheus-text-format metrics endpoint (IMP-03).

Hand-rolled exposition formatting — deliberately not using ``prometheus_client``
to stay dependency-light, per the production-readiness checklist. Reuses the
existing counters in ``app.core.routing_observability`` and the same
per-layer availability probes that back ``/health`` in ``main.py``, so there
is a single source of truth for both surfaces.

No message content or user identifiers are exposed here — only counts,
rates, latencies, and boolean/enum availability.
"""

from __future__ import annotations

from threading import Lock

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

router = APIRouter()

CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

_lock = Lock()
_request_count = 0
_request_duration_seconds_sum = 0.0


def observe_request_duration(seconds: float) -> None:
    """Record one request's wall-clock duration (count + sum, summary-style).

    Called from a lightweight ASGI middleware in ``main.py`` for every
    request — no per-router changes needed to opt in.
    """
    global _request_count, _request_duration_seconds_sum

    with _lock:
        _request_count += 1
        _request_duration_seconds_sum += seconds


def _request_metrics() -> tuple[int, float]:
    with _lock:
        return _request_count, _request_duration_seconds_sum


def _fmt(value: float | int) -> str:
    if isinstance(value, bool):  # bool is an int subclass — guard first
        return "1" if value else "0"
    return repr(float(value))


def _bool(value: bool) -> str:
    return "1" if value else "0"


def render_metrics(availability: dict[str, bool]) -> str:
    """Render current counters/gauges as Prometheus text exposition format.

    ``availability`` maps layer name (ollama, openrouter, embeddings,
    tool_router, rerank) to a boolean, mirroring ``/health``'s per-layer
    checks.
    """
    from app.core.routing_observability import get_stats

    stats = get_stats()
    request_count, request_duration_sum = _request_metrics()

    lines: list[str] = []

    lines.append("# HELP app_info Static application info.")
    lines.append("# TYPE app_info gauge")

    lines.append(
        "# HELP tool_router_deferrals_total Total tool-router classification calls deferred to the LLM."
    )
    lines.append("# TYPE tool_router_deferrals_total counter")
    lines.append(f"tool_router_deferrals_total {_fmt(stats['deferrals_total'])}")

    lines.append(
        "# HELP tool_router_near_misses_total Total deferrals whose top score was within the near-miss threshold."
    )
    lines.append("# TYPE tool_router_near_misses_total counter")
    lines.append(f"tool_router_near_misses_total {_fmt(stats['near_misses_total'])}")

    lines.append(
        "# HELP tool_router_near_miss_threshold Configured near-miss score threshold."
    )
    lines.append("# TYPE tool_router_near_miss_threshold gauge")
    lines.append(
        f"tool_router_near_miss_threshold {_fmt(stats['near_miss_threshold'])}"
    )

    lines.append(
        "# HELP layer_available Per-layer availability (1 = available, 0 = unavailable)."
    )
    lines.append("# TYPE layer_available gauge")
    for layer, ok in availability.items():
        lines.append(f'layer_available{{layer="{layer}"}} {_bool(ok)}')

    lines.append(
        "# HELP http_request_duration_seconds Wall-clock duration of HTTP requests handled by the app."
    )
    lines.append("# TYPE http_request_duration_seconds summary")
    lines.append(
        f"http_request_duration_seconds_count {_fmt(request_count)}"
    )
    lines.append(
        f"http_request_duration_seconds_sum {_fmt(request_duration_sum)}"
    )

    return "\n".join(lines) + "\n"


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics_endpoint() -> PlainTextResponse:
    """Expose Prometheus-text-format metrics (unauthenticated, like /health).

    Not gated behind API-key auth since external scrapers typically cannot
    present one — mirrors the existing ``/health`` endpoint's posture.
    """
    from main import _layer_availability

    availability = await _layer_availability()
    body = render_metrics(availability)
    return PlainTextResponse(content=body, media_type=CONTENT_TYPE_LATEST)
