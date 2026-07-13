"""SQLite persistence for knowledge collections and sources."""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

MigrationFn = Callable[[sqlite3.Connection], None]


def _current_knowledge_version(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='knowledge_schema_version'"
    ).fetchone()
    if row is None:
        return 0
    ver = conn.execute("SELECT version FROM knowledge_schema_version LIMIT 1").fetchone()
    if ver is None:
        return 0
    return int(ver[0])


def _ensure_version_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_schema_version (
            version INTEGER NOT NULL
        )
        """
    )
    count = conn.execute("SELECT COUNT(*) FROM knowledge_schema_version").fetchone()[0]
    if count == 0:
        conn.execute("INSERT INTO knowledge_schema_version (version) VALUES (0)")


def _set_knowledge_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute("DELETE FROM knowledge_schema_version")
    conn.execute(
        "INSERT INTO knowledge_schema_version (version) VALUES (?)",
        (version,),
    )


# Ordered, forward-only, idempotent migrations. Each function's index in this
# list is the schema version it upgrades *to* (i.e. migration i moves the db
# from version == i to version == i + 1). Never reorder or remove entries here
# — append new migrations to the end instead.
MIGRATIONS: list[MigrationFn] = []


class KnowledgeStore:
    """Persistence for per-person video/transcript knowledge collections."""

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
        """Ensure baseline tables and apply pending knowledge migrations.

        Migrations are idempotent and forward-only, tracked in
        ``knowledge_schema_version`` (not ``PRAGMA user_version``, which
        MemoryStore owns). All pending migrations commit together in one
        transaction when the ``with`` block exits.
        """
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_collections (
                    id TEXT PRIMARY KEY,
                    slug TEXT NOT NULL UNIQUE,
                    person_name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    embed_provider TEXT NOT NULL DEFAULT 'openrouter',
                    embed_model TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_sources (
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
                """
            )
            # NOTE: rows are written at ingest but retrieval reads only the in-memory
            # index (app/rag/retriever.py); this table is bookkeeping/inspection only.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_chunks (
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
                """
            )
            _ensure_version_table(conn)
            for version in range(_current_knowledge_version(conn), len(MIGRATIONS)):
                MIGRATIONS[version](conn)
                _set_knowledge_version(conn, version + 1)

    def create_collection(
        self,
        *,
        slug: str,
        person_name: str,
        title: str,
        description: str = "",
        embed_provider: str = "openrouter",
        embed_model: str = "",
        collection_id: str | None = None,
    ) -> Dict[str, Any]:
        cid = collection_id or str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_collections
                    (id, slug, person_name, title, description, embed_provider, embed_model)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (cid, slug, person_name, title, description, embed_provider, embed_model),
            )
        return self.get_collection(cid) or {}

    def get_collection(self, collection_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM knowledge_collections WHERE id = ? OR slug = ?",
                (collection_id, collection_id),
            ).fetchone()
        return dict(row) if row else None

    def list_collections(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.*,
                       COUNT(DISTINCT s.id) AS source_count,
                       COUNT(DISTINCT k.chunk_id) AS chunk_count
                FROM knowledge_collections c
                LEFT JOIN knowledge_sources s ON s.collection_id = c.id
                LEFT JOIN knowledge_chunks k ON k.collection_id = c.id
                GROUP BY c.id
                ORDER BY c.created_at
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_collection(self, collection_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM knowledge_collections WHERE id = ? OR slug = ?",
                (collection_id, collection_id),
            )
        return cursor.rowcount > 0

    def create_source(
        self,
        collection_id: str,
        *,
        title: str,
        source_type: str,
        uri: str = "",
        duration_sec: float | None = None,
        status: str = "pending",
        source_id: str | None = None,
    ) -> Dict[str, Any]:
        collection = self.get_collection(collection_id)
        if collection is None:
            raise ValueError(f"Collection not found: {collection_id}")
        sid = source_id or str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_sources
                    (id, collection_id, title, source_type, uri, duration_sec, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (sid, collection["id"], title, source_type, uri, duration_sec, status),
            )
        return self.get_source(sid) or {}

    def get_source(self, source_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM knowledge_sources WHERE id = ?",
                (source_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_sources(self, collection_id: str) -> List[Dict[str, Any]]:
        collection = self.get_collection(collection_id)
        if collection is None:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM knowledge_sources
                WHERE collection_id = ?
                ORDER BY created_at
                """,
                (collection["id"],),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_source_status(
        self,
        source_id: str,
        *,
        status: str,
        error_message: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE knowledge_sources
                SET status = ?, error_message = ?
                WHERE id = ?
                """,
                (status, error_message, source_id),
            )

    def replace_chunks_for_source(
        self,
        collection_id: str,
        source_id: str,
        chunks: List[Dict[str, Any]],
    ) -> int:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM knowledge_chunks WHERE source_id = ?",
                (source_id,),
            )
            for chunk in chunks:
                conn.execute(
                    """
                    INSERT INTO knowledge_chunks
                        (chunk_id, collection_id, source_id, text,
                         start_sec, end_sec, embed_profile_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk["chunk_id"],
                        collection_id,
                        source_id,
                        chunk["text"],
                        chunk.get("start_sec"),
                        chunk.get("end_sec"),
                        chunk.get("embed_profile_id", ""),
                    ),
                )
        return len(chunks)

    def clear_all(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM knowledge_chunks")
            conn.execute("DELETE FROM knowledge_sources")
            conn.execute("DELETE FROM knowledge_collections")

    def collection_dir(self, slug: str, base_dir: str) -> Path:
        path = Path(base_dir) / slug
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_collection_json(self, slug: str, base_dir: str, payload: Dict[str, Any]) -> Path:
        directory = self.collection_dir(slug, base_dir)
        target = directory / "collection.json"
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return target
