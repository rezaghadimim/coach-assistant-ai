"""SQLite-backed persistence for users, sessions, and chat messages."""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


class MemoryStore:
    """Persistence layer for user profiles and coaching sessions."""

    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    name TEXT,
                    profile_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    ended_at TEXT,
                    summary TEXT,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS client_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    session_id TEXT,
                    note_type TEXT NOT NULL DEFAULT 'general',
                    title TEXT,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(user_id),
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                )
                """
            )

    def upsert_user(
        self,
        user_id: str,
        *,
        name: Optional[str] = None,
        profile: Optional[Dict[str, Any]] = None,
    ) -> None:
        profile_json = json.dumps(profile or {}, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, name, profile_json)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    name=COALESCE(excluded.name, users.name),
                    profile_json=excluded.profile_json
                """,
                (user_id, name, profile_json),
            )

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id, name, profile_json FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()

        if row is None:
            return None
        return {
            "user_id": row["user_id"],
            "name": row["name"],
            "profile": json.loads(row["profile_json"] or "{}"),
        }

    def create_session(self, user_id: str) -> str:
        session_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (session_id, user_id) VALUES (?, ?)",
                (session_id, user_id),
            )
        return session_id

    def get_latest_open_session(self, user_id: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT session_id
                FROM sessions
                WHERE user_id = ? AND ended_at IS NULL
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
        return row["session_id"] if row else None

    def get_last_closed_summary(self, user_id: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT summary
                FROM sessions
                WHERE user_id = ? AND ended_at IS NOT NULL AND summary IS NOT NULL
                ORDER BY ended_at DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return row["summary"]

    def add_message(self, session_id: str, role: str, content: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
                (session_id, role, content),
            )

    def get_session_messages(self, session_id: str) -> list[dict[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT role, content
                FROM messages
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()

        return [{"role": row["role"], "content": row["content"]} for row in rows]

    def count_session_messages(self, session_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return int(row["count"]) if row else 0

    def update_session_summary(self, session_id: str, summary: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET summary = ? WHERE session_id = ?",
                (summary, session_id),
            )

    def end_session(self, session_id: str, summary: Optional[str] = None) -> None:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE sessions
                SET ended_at = CURRENT_TIMESTAMP,
                    summary = COALESCE(?, summary)
                WHERE session_id = ? AND ended_at IS NULL
                """,
                (summary, session_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Session does not exist or is already ended: {session_id}")


    def clear_all_data(self) -> None:
        """Delete all persisted users, sessions, and messages."""
        with self._connect() as conn:
            conn.execute("DELETE FROM client_notes")
            conn.execute("DELETE FROM messages")
            conn.execute("DELETE FROM sessions")
            conn.execute("DELETE FROM users")

    def list_sessions(self, user_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT session_id, user_id, started_at, ended_at, summary
                FROM sessions
                WHERE user_id = ?
                ORDER BY started_at DESC
                """,
                (user_id,),
            ).fetchall()

        return [
            {
                "session_id": row["session_id"],
                "user_id": row["user_id"],
                "started_at": row["started_at"],
                "ended_at": row["ended_at"],
                "summary": row["summary"],
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Client notes (per-client documentation, stories, decisions)
    # ------------------------------------------------------------------

    def add_client_note(
        self,
        user_id: str,
        content: str,
        *,
        note_type: str = "general",
        title: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> int:
        """Add a note for a client. Returns the note id."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO client_notes (user_id, session_id, note_type, title, content)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, session_id, note_type, title, content),
            )
            return cursor.lastrowid  # type: ignore[return-value]

    def update_client_note(
        self,
        note_id: int,
        content: str,
        *,
        title: Optional[str] = None,
        note_type: Optional[str] = None,
    ) -> bool:
        """Update an existing note. Returns True if the note was found."""
        parts = ["content = ?", "updated_at = CURRENT_TIMESTAMP"]
        params: list[Any] = [content]
        if title is not None:
            parts.append("title = ?")
            params.append(title)
        if note_type is not None:
            parts.append("note_type = ?")
            params.append(note_type)
        params.append(note_id)
        with self._connect() as conn:
            cursor = conn.execute(
                f"UPDATE client_notes SET {', '.join(parts)} WHERE id = ?",
                params,
            )
            return cursor.rowcount > 0

    def get_client_notes(
        self,
        user_id: str,
        note_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return all notes for a client, optionally filtered by type."""
        query = """
            SELECT id, user_id, session_id, note_type, title, content,
                   created_at, updated_at
            FROM client_notes
            WHERE user_id = ?
        """
        params: list[Any] = [user_id]
        if note_type:
            query += " AND note_type = ?"
            params.append(note_type)
        query += " ORDER BY updated_at DESC"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()

        return [
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "session_id": row["session_id"],
                "note_type": row["note_type"],
                "title": row["title"],
                "content": row["content"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def list_users(self) -> List[Dict[str, Any]]:
        """Return all registered users/clients."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT user_id, name, profile_json, created_at FROM users ORDER BY created_at DESC"
            ).fetchall()
        return [
            {
                "user_id": row["user_id"],
                "name": row["name"],
                "profile": json.loads(row["profile_json"] or "{}"),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def delete_client_note(self, note_id: int) -> bool:
        """Delete a note by id. Returns True if the note existed."""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM client_notes WHERE id = ?", (note_id,)
            )
            return cursor.rowcount > 0
