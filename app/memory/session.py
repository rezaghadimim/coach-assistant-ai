"""Session lifecycle helpers for per-user coaching sessions."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from app.core.config import settings
from app.memory.store import MemoryStore
from app.memory.summarizer import summarize_session

logger = logging.getLogger(__name__)


class SessionManager:
    """Tracks active session IDs and coordinates session rollover."""

    def __init__(self, store: MemoryStore) -> None:
        self.store = store
        self._active_sessions: dict[str, str] = {}
        # Highest threshold boundary already summarized per session. Keeps the
        # summarizer from re-running its LLM call on every message past the
        # threshold — it fires once per crossed boundary (20, 40, 60, ...).
        self._summarized_boundary: dict[str, int] = {}
        # Strong references to in-flight background summary tasks (asyncio only
        # keeps weak references; without this the task can be GC'd mid-run).
        self._summary_tasks: set[asyncio.Task] = set()

    def reset(self) -> None:
        """Clear in-memory active session cache."""
        self._active_sessions.clear()
        self._summarized_boundary.clear()

    def get_or_create_session_id(
        self,
        user_id: str,
        *,
        coach_name: Optional[str] = None,
    ) -> str:
        self.store.upsert_user(user_id, name=coach_name, is_coach=True)

        if user_id in self._active_sessions:
            return self._active_sessions[user_id]

        existing = self.store.get_latest_open_session(user_id)
        if existing:
            self._active_sessions[user_id] = existing
            return existing

        created = self.store.create_session(user_id)
        self._active_sessions[user_id] = created
        return created

    async def start_new_session(
        self,
        user_id: str,
        *,
        coach_name: Optional[str] = None,
    ) -> str:
        self.store.upsert_user(user_id, name=coach_name, is_coach=True)

        old_session = self._active_sessions.get(user_id) or self.store.get_latest_open_session(user_id)
        if old_session:
            messages = self.store.get_session_messages(old_session)
            summary = await summarize_session(messages) if messages else None
            self.store.end_session(old_session, summary=summary)
            self._summarized_boundary.pop(old_session, None)

        new_session = self.store.create_session(user_id)
        self._active_sessions[user_id] = new_session
        return new_session

    async def maybe_update_summary(self, session_id: str, threshold: int) -> None:
        """Summarize the session once per crossed threshold boundary.

        Idempotent: repeated calls between boundaries (e.g. messages 20-39
        with threshold 20) run the LLM summarizer only once.
        """
        count = self.store.count_session_messages(session_id)
        if count < threshold:
            return
        boundary = (count // threshold) * threshold
        if self._summarized_boundary.get(session_id, 0) >= boundary:
            return
        # Claim the boundary before the slow LLM call so concurrent requests
        # in the same event loop don't both dispatch a summarization.
        self._summarized_boundary[session_id] = boundary
        try:
            messages = self.store.get_session_messages(session_id)
            summary = await summarize_session(messages)
            self.store.update_session_summary(session_id, summary)
        except Exception:
            # Release the claim so the next boundary check retries.
            if self._summarized_boundary.get(session_id) == boundary:
                self._summarized_boundary.pop(session_id, None)
            raise

    def schedule_update_summary(self, session_id: str, threshold: int) -> None:
        """Run ``maybe_update_summary`` in the background, off the request path.

        The task carries its own timeout so a hung LLM call cannot pile up
        background work; failures are logged, never raised into a request.
        """
        if self.store.count_session_messages(session_id) < threshold:
            return

        async def _run() -> None:
            try:
                await asyncio.wait_for(
                    self.maybe_update_summary(session_id, threshold),
                    timeout=settings.summary_timeout_s,
                )
            except Exception:
                logger.warning(
                    "background summarization failed for session %s",
                    session_id,
                    exc_info=True,
                )

        task = asyncio.create_task(_run())
        self._summary_tasks.add(task)
        task.add_done_callback(self._summary_tasks.discard)
