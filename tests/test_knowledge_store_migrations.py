"""Regression tests for KnowledgeStore schema migrations and PRAGMA parity."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app.knowledge import store as knowledge_store_module
from app.knowledge.store import KnowledgeStore, MIGRATIONS
from app.memory.store import MemoryStore


def _legacy_knowledge_schema_sql() -> list[str]:
    """Pre-migration schema: three knowledge tables, no version table."""
    return [
        """
        CREATE TABLE knowledge_collections (
            id TEXT PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            person_name TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            embed_provider TEXT NOT NULL DEFAULT 'openrouter',
            embed_model TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE knowledge_sources (
            id TEXT PRIMARY KEY,
            collection_id TEXT NOT NULL,
            title TEXT NOT NULL,
            source_type TEXT NOT NULL,
            uri TEXT NOT NULL DEFAULT '',
            duration_sec REAL,
            status TEXT NOT NULL DEFAULT 'pending',
            error_message TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(collection_id) REFERENCES knowledge_collections(id)
                ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE knowledge_chunks (
            chunk_id TEXT PRIMARY KEY,
            collection_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            text TEXT NOT NULL,
            start_sec REAL,
            end_sec REAL,
            embed_profile_id TEXT NOT NULL DEFAULT '',
            indexed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(collection_id) REFERENCES knowledge_collections(id)
                ON DELETE CASCADE,
            FOREIGN KEY(source_id) REFERENCES knowledge_sources(id)
                ON DELETE CASCADE
        )
        """,
    ]


class KnowledgeStoreMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.db_path = tmp.name
        os.unlink(self.db_path)

    def tearDown(self) -> None:
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def _query(self, sql: str, params: tuple = ()):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def _table_names(self) -> set[str]:
        rows = self._query(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        return {row["name"] for row in rows}

    def _knowledge_version(self) -> int:
        row = self._query("SELECT version FROM knowledge_schema_version LIMIT 1")
        return int(row[0]["version"]) if row else 0

    def _user_version(self) -> int:
        return int(self._query("PRAGMA user_version")[0][0])

    def _build_legacy_knowledge_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            for statement in _legacy_knowledge_schema_sql():
                conn.execute(statement)
            conn.execute(
                """
                INSERT INTO knowledge_collections
                    (id, slug, person_name, title)
                VALUES ('c1', 'legacy', 'Legacy Person', 'Legacy Title')
                """
            )
            conn.commit()
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            self.assertNotIn("knowledge_schema_version", tables)
        finally:
            conn.close()

    def test_fresh_db_initializes_at_version_zero(self) -> None:
        KnowledgeStore(self.db_path)

        self.assertEqual(self._knowledge_version(), 0)
        self.assertEqual(len(MIGRATIONS), 0)
        self.assertEqual(
            self._table_names(),
            {
                "knowledge_chunks",
                "knowledge_collections",
                "knowledge_schema_version",
                "knowledge_sources",
            },
        )

    def test_dummy_migration_applies_and_bumps_version(self) -> None:
        def _migration_add_test_column(conn: sqlite3.Connection) -> None:
            conn.execute(
                "ALTER TABLE knowledge_collections ADD COLUMN test_col TEXT DEFAULT ''"
            )

        with patch.object(
            knowledge_store_module,
            "MIGRATIONS",
            [_migration_add_test_column],
        ):
            KnowledgeStore(self.db_path)

        self.assertEqual(self._knowledge_version(), 1)
        columns = {
            row["name"] for row in self._query("PRAGMA table_info(knowledge_collections)")
        }
        self.assertIn("test_col", columns)

    def test_legacy_db_without_version_table_upgrades_cleanly(self) -> None:
        self._build_legacy_knowledge_db()

        store = KnowledgeStore(self.db_path)

        self.assertEqual(self._knowledge_version(), 0)
        self.assertIn("knowledge_schema_version", self._table_names())
        collections = store.list_collections()
        self.assertEqual(len(collections), 1)
        self.assertEqual(collections[0]["slug"], "legacy")

    def test_coexists_with_memory_store_without_touching_user_version(self) -> None:
        MemoryStore(self.db_path)
        user_version_after_memory = self._user_version()

        KnowledgeStore(self.db_path)

        self.assertEqual(self._user_version(), user_version_after_memory)
        self.assertEqual(self._knowledge_version(), 0)
        # MemoryStore remains usable on the shared file after KnowledgeStore init.
        MemoryStore(self.db_path)


if __name__ == "__main__":
    unittest.main()
