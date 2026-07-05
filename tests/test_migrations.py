"""Regression tests for the MemoryStore schema migration runner."""

import os
import sqlite3
import tempfile
import unittest

from app.memory.store import MIGRATIONS, MemoryStore


def _legacy_schema_sql() -> list[str]:
    """The pre-migration schema: base tables, users without is_coach."""
    return [
        """
        CREATE TABLE users (
            user_id TEXT PRIMARY KEY,
            name TEXT,
            profile_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            ended_at TEXT,
            summary TEXT,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
        """,
        """
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(session_id) REFERENCES sessions(session_id)
        )
        """,
        """
        CREATE TABLE client_notes (
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
        """,
    ]


class MigrationRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.db_path = tmp.name
        os.unlink(self.db_path)  # start from a truly empty path

    def tearDown(self) -> None:
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def _build_legacy_db(self, *, with_is_coach: bool = False) -> None:
        """Hand-build a legacy database at PRAGMA user_version = 0."""
        conn = sqlite3.connect(self.db_path)
        try:
            for statement in _legacy_schema_sql():
                conn.execute(statement)
            if with_is_coach:
                conn.execute(
                    "ALTER TABLE users ADD COLUMN is_coach INTEGER NOT NULL DEFAULT 0"
                )
            conn.execute(
                "INSERT INTO users (user_id, name) VALUES ('coach-1', 'Reza')"
            )
            conn.execute(
                "INSERT INTO users (user_id, name) VALUES ('ali', 'Ali')"
            )
            conn.execute(
                "INSERT INTO sessions (session_id, user_id) VALUES ('s1', 'coach-1')"
            )
            conn.execute(
                "INSERT INTO messages (session_id, role, content) "
                "VALUES ('s1', 'user', 'hello')"
            )
            conn.execute(
                "INSERT INTO client_notes (user_id, content) VALUES ('ali', 'a goal')"
            )
            self.assertEqual(
                int(conn.execute("PRAGMA user_version").fetchone()[0]), 0
            )
            conn.commit()
        finally:
            conn.close()

    def _query(self, sql: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(sql).fetchall()
        finally:
            conn.close()

    def _user_version(self) -> int:
        return int(self._query("PRAGMA user_version")[0][0])

    def _user_columns(self) -> set:
        return {row["name"] for row in self._query("PRAGMA table_info(users)")}

    def test_legacy_db_converges_to_current_schema(self) -> None:
        self._build_legacy_db()

        store = MemoryStore(self.db_path)

        self.assertEqual(self._user_version(), len(MIGRATIONS))
        self.assertIn("is_coach", self._user_columns())

        # Rows preserved, and the backfill marked the session owner a coach.
        users = {row["user_id"]: row for row in self._query("SELECT * FROM users")}
        self.assertEqual(set(users), {"coach-1", "ali"})
        self.assertEqual(users["coach-1"]["is_coach"], 1)
        self.assertEqual(users["ali"]["is_coach"], 0)
        self.assertEqual(len(self._query("SELECT * FROM sessions")), 1)
        self.assertEqual(len(self._query("SELECT * FROM messages")), 1)
        self.assertEqual(len(self._query("SELECT * FROM client_notes")), 1)

        # The store is actually usable against the migrated schema.
        self.assertIsNotNone(store.get_user("ali"))

    def test_second_open_is_a_noop(self) -> None:
        self._build_legacy_db()
        MemoryStore(self.db_path)
        first_users = [tuple(row) for row in self._query("SELECT * FROM users")]

        MemoryStore(self.db_path)

        self.assertEqual(self._user_version(), len(MIGRATIONS))
        second_users = [tuple(row) for row in self._query("SELECT * FROM users")]
        self.assertEqual(second_users, first_users)

    def test_legacy_db_with_is_coach_is_not_double_backfilled(self) -> None:
        """A legacy db that already has is_coach keeps its values verbatim:
        the migration must not re-run the session-owner backfill."""
        self._build_legacy_db(with_is_coach=True)

        MemoryStore(self.db_path)

        self.assertEqual(self._user_version(), len(MIGRATIONS))
        users = {row["user_id"]: row for row in self._query("SELECT * FROM users")}
        # coach-1 owns a session but its pre-existing is_coach=0 is preserved —
        # the backfill only runs when the column itself is being added.
        self.assertEqual(users["coach-1"]["is_coach"], 0)
        self.assertEqual(users["ali"]["is_coach"], 0)

    def test_fresh_db_reaches_current_version(self) -> None:
        MemoryStore(self.db_path)
        self.assertEqual(self._user_version(), len(MIGRATIONS))
        self.assertIn("is_coach", self._user_columns())


if __name__ == "__main__":
    unittest.main()
