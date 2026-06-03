# ADR-0004: SQLite for Session and Memory Persistence

**Date:** 2024-01-01
**Status:** Accepted

## Context

Phase 3 requires persistent storage for:

- **Users** — profile information and coaching goals.
- **Sessions** — per-user conversation sessions with start/end timestamps and summaries.
- **Messages** — individual turns within each session.

Requirements:

- Zero-configuration, file-based persistence (no separate database server to install).
- Sufficient query capability for per-user session lookup and message retrieval.
- Works within the same Python process as the FastAPI application.
- Simple backup story — copy one file.

## Decision

Use **SQLite** via Python's built-in `sqlite3` module. The database is stored at a configurable path (default `data/life_coach.db`) and managed entirely within `app/memory/store.py`.

## Consequences

**Positive:**
- No additional install steps — SQLite ships with Python.
- Single-file database is trivially portable and easy to back up.
- ACID transactions ensure message consistency even if the process is interrupted.
- Sufficient performance for a single-user local coaching application.

**Negative:**
- Write concurrency is limited (SQLite uses file-level locking). Not suitable for multi-user production deployments.
- No built-in full-text search (FTS5 is available but not wired up).
- Schema migrations must be handled manually if the schema evolves.

## Alternatives Considered

| Option | Reason Not Chosen |
|--------|------------------|
| PostgreSQL | Requires a separate server process; excessive for single-user local use |
| Redis | In-memory only (without persistence config); better suited for cache/pub-sub than relational data |
| Plain JSON files | No transactional guarantees; harder to query across sessions |
| SQLAlchemy ORM | Adds abstraction overhead; raw `sqlite3` is readable and sufficient |

## Future Direction

If the application is deployed as a multi-tenant service, replace SQLite with PostgreSQL. The `MemoryStore` class (`app/memory/store.py`) provides a clean boundary for this swap.
