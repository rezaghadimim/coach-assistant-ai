"""Concurrency hardening regression tests.

REL-02 — SQLite WAL + busy_timeout: concurrent writers must not raise
``sqlite3.OperationalError: database is locked``.

REL-03 — a lock around SessionManager.get_or_create_session_id: concurrent
same-user calls must yield exactly one session id (no duplicate sessions).
"""

from __future__ import annotations

import sqlite3
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from app.memory.session import SessionManager
from app.memory.store import MemoryStore


class SqliteConcurrentWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._dir = tempfile.TemporaryDirectory()
        self.store = MemoryStore(f"{self._dir.name}/concurrency.db")

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_concurrent_writers_do_not_lock(self) -> None:
        self.store.upsert_user("coach", is_coach=True)
        session_id = self.store.create_session("coach")

        errors: list[Exception] = []
        barrier = threading.Barrier(8)

        def writer(worker: int) -> None:
            barrier.wait()  # release all writers simultaneously
            try:
                for i in range(25):
                    self.store.add_message(session_id, "user", f"w{worker}-{i}")
            except sqlite3.OperationalError as exc:  # pragma: no cover - failure path
                errors.append(exc)

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(writer, range(8)))

        self.assertEqual(errors, [], f"writers hit lock errors: {errors}")
        self.assertEqual(len(self.store.get_session_messages(session_id)), 8 * 25)

    def test_wal_mode_enabled(self) -> None:
        conn = self.store._connect()
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(mode.lower(), "wal")


class SessionManagerConcurrencyTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._dir = tempfile.TemporaryDirectory()
        self.store = MemoryStore(f"{self._dir.name}/sessions.db")
        self.manager = SessionManager(self.store)

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_concurrent_same_user_yields_single_session(self) -> None:
        barrier = threading.Barrier(16)

        def get_session(_: int) -> str:
            barrier.wait()
            return self.manager.get_or_create_session_id("coach-1")

        with ThreadPoolExecutor(max_workers=16) as pool:
            ids = list(pool.map(get_session, range(16)))

        self.assertEqual(len(set(ids)), 1, f"multiple sessions created: {set(ids)}")
        # And the store must hold exactly one session row for the user.
        conn = self.store._connect()
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE user_id = ?", ("coach-1",)
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
