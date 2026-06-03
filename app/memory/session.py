"""Session lifecycle helpers for per-user coaching sessions."""

from app.memory.store import MemoryStore
from app.memory.summarizer import summarize_session


class SessionManager:
    """Tracks active session IDs and coordinates session rollover."""

    def __init__(self, store: MemoryStore) -> None:
        self.store = store
        self._active_sessions: dict[str, str] = {}

    def reset(self) -> None:
        """Clear in-memory active session cache."""
        self._active_sessions.clear()

    def get_or_create_session_id(self, user_id: str) -> str:
        if user_id in self._active_sessions:
            return self._active_sessions[user_id]

        existing = self.store.get_latest_open_session(user_id)
        if existing:
            self._active_sessions[user_id] = existing
            return existing

        self.store.upsert_user(user_id)
        created = self.store.create_session(user_id)
        self._active_sessions[user_id] = created
        return created

    def start_new_session(self, user_id: str) -> str:
        old_session = self._active_sessions.get(user_id) or self.store.get_latest_open_session(user_id)
        if old_session:
            messages = self.store.get_session_messages(old_session)
            summary = summarize_session(messages) if messages else None
            self.store.end_session(old_session, summary=summary)

        self.store.upsert_user(user_id)
        new_session = self.store.create_session(user_id)
        self._active_sessions[user_id] = new_session
        return new_session

    def maybe_update_summary(self, session_id: str, threshold: int) -> None:
        if self.store.count_session_messages(session_id) < threshold:
            return
        messages = self.store.get_session_messages(session_id)
        self.store.update_session_summary(session_id, summarize_session(messages))
