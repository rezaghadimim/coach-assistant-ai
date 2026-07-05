"""SQLite-backed persistence for users, sessions, and chat messages."""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


def _current_user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _migration_0_initial_schema(conn: sqlite3.Connection) -> None:
    """Create the base tables (users, sessions, messages, client_notes)."""
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


def _migration_1_add_is_coach_column(conn: sqlite3.Connection) -> None:
    """Add is_coach flag and backfill coach rows from existing sessions."""
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()
    }
    if "is_coach" not in columns:
        conn.execute(
            "ALTER TABLE users ADD COLUMN is_coach INTEGER NOT NULL DEFAULT 0"
        )
        conn.execute(
            """
            UPDATE users
            SET is_coach = 1
            WHERE user_id IN (SELECT DISTINCT user_id FROM sessions)
            """
        )


# Ordered, forward-only, idempotent migrations. Each function's index in this
# list is the schema version it upgrades *to* (i.e. migration i moves the db
# from user_version == i to user_version == i + 1). Never reorder or remove
# entries here — append new migrations to the end instead.
MIGRATIONS = [
    _migration_0_initial_schema,
    _migration_1_add_is_coach_column,
]


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
        # busy_timeout must be set *before* the journal_mode switch: changing
        # journal mode itself takes an exclusive lock, and with multiple
        # uvicorn workers starting concurrently (each running _init_schema on
        # import) two processes can race for that lock. Without busy_timeout
        # already active on this connection, the loser fails immediately with
        # "database is locked" instead of waiting for the winner to finish.
        conn.execute("PRAGMA busy_timeout = 5000")
        # WAL lets readers run concurrently with a single writer (default
        # rollback journal blocks both).
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _init_schema(self) -> None:
        """Apply any pending migrations, tracked via ``PRAGMA user_version``.

        Migrations are idempotent and forward-only. All pending migrations
        (and their ``user_version`` bumps) commit together in one transaction
        when the ``with`` block exits: a mid-list failure rolls the whole run
        back to the starting version, and the next open re-runs the full
        pending list from there.
        """
        with self._connect() as conn:
            for version in range(_current_user_version(conn), len(MIGRATIONS)):
                MIGRATIONS[version](conn)
                conn.execute(f"PRAGMA user_version = {version + 1}")

    def upsert_user(
        self,
        user_id: str,
        *,
        name: Optional[str] = None,
        profile: Optional[Dict[str, Any]] = None,
        is_coach: Optional[bool] = None,
    ) -> None:
        with self._connect() as conn:
            if profile is None and is_coach is None:
                conn.execute(
                    """
                    INSERT INTO users (user_id, name, profile_json)
                    VALUES (?, ?, '{}')
                    ON CONFLICT(user_id) DO UPDATE SET
                        name=COALESCE(excluded.name, users.name)
                    """,
                    (user_id, name),
                )
                return

            profile_json = json.dumps(profile or {}, ensure_ascii=False)
            if is_coach is None:
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
            else:
                conn.execute(
                    """
                    INSERT INTO users (user_id, name, profile_json, is_coach)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        name=COALESCE(excluded.name, users.name),
                        profile_json=CASE
                            WHEN excluded.profile_json != '{}'
                                OR users.profile_json IS NULL
                            THEN excluded.profile_json
                            ELSE users.profile_json
                        END,
                        is_coach=excluded.is_coach
                    """,
                    (user_id, name, profile_json, int(is_coach)),
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

    def list_all_sessions(self, *, ended_only: bool = False) -> list[dict[str, Any]]:
        """Return sessions across all users, optionally limited to closed sessions."""
        query = """
            SELECT session_id, user_id, started_at, ended_at, summary
            FROM sessions
        """
        if ended_only:
            query += " WHERE ended_at IS NOT NULL"
        query += " ORDER BY started_at ASC"

        with self._connect() as conn:
            rows = conn.execute(query).fetchall()

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
        user_id: Optional[str] = None,
    ) -> bool:
        """Update an existing note. Returns True if the note was found.

        When ``user_id`` is given, only a note owned by that client is
        updated — callers holding a caller-supplied client id (the HTTP API)
        must pass it so a note id cannot be mutated across clients.
        """
        parts = ["content = ?", "updated_at = CURRENT_TIMESTAMP"]
        params: list[Any] = [content]
        if title is not None:
            parts.append("title = ?")
            params.append(title)
        if note_type is not None:
            parts.append("note_type = ?")
            params.append(note_type)
        params.append(note_id)
        where = "id = ?"
        if user_id is not None:
            where += " AND user_id = ?"
            params.append(user_id)
        with self._connect() as conn:
            cursor = conn.execute(
                f"UPDATE client_notes SET {', '.join(parts)} WHERE {where}",
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

    def list_users(self, *, clients_only: bool = False) -> List[Dict[str, Any]]:
        """Return registered users; optionally exclude coach session accounts."""
        query = (
            "SELECT user_id, name, profile_json, created_at FROM users "
            "WHERE COALESCE(is_coach, 0) = 0 "
            if clients_only
            else "SELECT user_id, name, profile_json, created_at FROM users "
        )
        query += "ORDER BY created_at DESC"
        with self._connect() as conn:
            rows = conn.execute(query).fetchall()
        return [
            {
                "user_id": row["user_id"],
                "name": row["name"],
                "profile": json.loads(row["profile_json"] or "{}"),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def get_client_note(self, note_id: int) -> Optional[Dict[str, Any]]:
        """Return one note by id, or None if it does not exist."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, user_id, session_id, note_type, title, content,
                       created_at, updated_at
                FROM client_notes
                WHERE id = ?
                """,
                (note_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "session_id": row["session_id"],
            "note_type": row["note_type"],
            "title": row["title"],
            "content": row["content"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def delete_client_note(self, note_id: int, *, user_id: Optional[str] = None) -> bool:
        """Delete a note by id. Returns True if the note existed.

        When ``user_id`` is given, only a note owned by that client is deleted
        (see ``update_client_note``).
        """
        query = "DELETE FROM client_notes WHERE id = ?"
        params: list[Any] = [note_id]
        if user_id is not None:
            query += " AND user_id = ?"
            params.append(user_id)
        with self._connect() as conn:
            cursor = conn.execute(query, params)
            return cursor.rowcount > 0

    def delete_user(self, user_id: str) -> bool:
        """Delete a client and their notes. Sessions/messages are kept orphaned-free."""
        with self._connect() as conn:
            conn.execute("DELETE FROM client_notes WHERE user_id = ?", (user_id,))
            conn.execute(
                """
                DELETE FROM messages
                WHERE session_id IN (
                    SELECT session_id FROM sessions WHERE user_id = ?
                )
                """,
                (user_id,),
            )
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            cursor = conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            return cursor.rowcount > 0
