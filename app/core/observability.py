"""Centralised logging bootstrap, context propagation, and step-log helpers.

Usage
-----
Call ``setup_logging()`` once at application startup (before FastAPI/uvicorn
starts serving requests).  Every request handler should then call
``bind_message(user_id)`` to attach a short correlation id and the user to
every log record produced within that request.  Call ``reset_message()`` in a
``finally`` block when the handler returns.

Step logging::

    from app.core.observability import log_step
    log_step(logger, "tool_router.rerank", "hit", tool="get_client", score=0.81)
    # → INFO  [msg=ab12cd user=alice] app.core.tool_router: step=tool_router.rerank outcome=hit tool=get_client score=0.81

Outcome vocabulary (use these strings so you can grep/count reliably)::

    hit | miss | skip | block | ok | preview | error | fail | fallback | hallucination
"""

from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Context variables — injected into every log record by ContextFilter
# ---------------------------------------------------------------------------

_msg_id: ContextVar[str] = ContextVar("_msg_id", default="-")
_user: ContextVar[str] = ContextVar("_user", default="-")


def bind_message(user_id: str) -> str:
    """Bind a new 6-char correlation id + user to the current context.

    Returns the generated msg_id so the caller can include it in its own
    start/done log lines.  Call ``reset_message`` in a ``finally`` block to
    restore the previous values.
    """
    msg_id = uuid.uuid4().hex[:6]
    _msg_id.set(msg_id)
    _user.set(user_id or "-")
    return msg_id


def rebind_message(msg_id: str, user_id: str) -> None:
    """Re-attach an existing correlation id + user to the current context.

    Used by streaming handlers: the request coroutine returns (and its context
    is reset) before the response generator runs, so the generator re-binds the
    original ``msg_id`` at its start to keep log lines correlated.
    """
    _msg_id.set(msg_id or "-")
    _user.set(user_id or "-")


def reset_message() -> None:
    """Reset the per-message context to defaults ("-")."""
    _msg_id.set("-")
    _user.set("-")


# ---------------------------------------------------------------------------
# Log filter — injects msg_id + user into every record
# ---------------------------------------------------------------------------


class _ContextFilter(logging.Filter):
    """Attach ``msg_id`` and ``user`` from contextvars to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg_id = _msg_id.get()  # type: ignore[attr-defined]
        record.user = _user.get()       # type: ignore[attr-defined]
        return True


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

_LOG_FORMAT = "%(asctime)s %(levelname)-5s [msg=%(msg_id)s user=%(user)s] %(name)s %(filename)s:%(lineno)d: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _attach_error_file_handler(root: logging.Logger, path: str) -> None:
    """Append an ERROR-only file handler if *path* is set and not already attached."""
    if not path:
        return
    for handler in root.handlers:
        if getattr(handler, "_coach_error_file", False):
            return

    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.ERROR)
    file_handler.addFilter(_ContextFilter())
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    file_handler._coach_error_file = True  # type: ignore[attr-defined]
    root.addHandler(file_handler)


def setup_logging(level: str | None = None) -> None:
    """Configure the root logger with a stdout handler and optional error file.

    Safe to call multiple times — subsequent calls are no-ops unless *level*
    changes.  Pass ``level`` to override ``settings.log_level``.
    """
    from app.core.config import settings

    if level is None:
        level = settings.log_level

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    root = logging.getLogger()
    # If we already attached our handler, update levels and ensure file handler exists.
    for handler in root.handlers:
        if getattr(handler, "_coach_observability", False):
            root.setLevel(numeric_level)
            handler.setLevel(numeric_level)
            _attach_error_file_handler(root, settings.log_error_file)
            return

    # Remove any stale handlers (e.g. from a previous uvicorn reload).
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(numeric_level)
    handler.addFilter(_ContextFilter())
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    handler._coach_observability = True  # type: ignore[attr-defined]

    root.setLevel(numeric_level)
    root.addHandler(handler)
    _attach_error_file_handler(root, settings.log_error_file)

    # Keep uvicorn's own loggers in sync so their output uses our format.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def log_step(
    logger: logging.Logger,
    step: str,
    outcome: str,
    *,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """Emit a single-line step log in ``step=<step> outcome=<outcome> k=v ...`` format.

    Uses ``stacklevel=2`` so the logged filename and line number point to the
    **caller** of ``log_step``, not to this module — making log lines directly
    copyable and navigable in the IDE.

    Example::

        log_step(logger, "tool_router.rerank", "hit", tool="get_client", score=0.81)
        # → … tool_router.py:338: step=tool_router.rerank outcome=hit tool=get_client score=0.810
    """
    parts = [f"step={step}", f"outcome={outcome}"]
    for key, value in fields.items():
        if isinstance(value, float):
            parts.append(f"{key}={value:.3f}")
        else:
            parts.append(f"{key}={value!r}" if isinstance(value, str) and " " in str(value) else f"{key}={value}")
    logger.log(level, " ".join(parts), stacklevel=2)


def preview(text: str, n: int = 80) -> str:
    """Return a safe short snippet of *text*, truncated to *n* chars."""
    if not text:
        return ""
    text = text.replace("\n", " ").strip()
    return text[:n] + "…" if len(text) > n else text
