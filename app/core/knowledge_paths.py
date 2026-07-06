"""Resolve RAG knowledge directories (committed starter + local private content)."""

from __future__ import annotations

from pathlib import Path

from app.core.config import settings


def knowledge_starter_dir() -> Path:
    """Return the committed starter (bundled) knowledge directory."""
    return Path(settings.rag_knowledge_starter_dir).expanduser().resolve()


def knowledge_private_dir() -> Path:
    """Return the local-only private knowledge directory path."""
    return Path(settings.rag_knowledge_private_dir).expanduser().resolve()


def knowledge_private_dir_if_exists() -> Path | None:
    """Return the private knowledge directory when it exists on disk."""
    path = knowledge_private_dir()
    return path if path.is_dir() else None


def collections_public_dir() -> Path:
    """Return the public (demo/seed) collections directory path."""
    return Path(settings.rag_collections_dir).expanduser().resolve()


def collections_private_dir() -> Path:
    """Return the private (real data) collections directory path."""
    return Path(settings.rag_collections_private_dir).expanduser().resolve()


def collection_dirs() -> list[Path]:
    """Collection roots to ingest, in order: public demos then private real data.

    Only existing directories are returned. The private dir lives inside the
    knowledge submodule and is absent until the submodule is initialized.
    """
    roots: list[Path] = []
    for path in (collections_public_dir(), collections_private_dir()):
        if path.is_dir() and path not in roots:
            roots.append(path)
    return roots


def knowledge_ingest_summary() -> str:
    """Human-readable description of which knowledge roots are indexed."""
    starter = knowledge_starter_dir()
    private = knowledge_private_dir_if_exists()
    if private is None:
        return str(starter)
    return f"{starter} + {private}"


# Backward-compatible alias (deprecated name).
knowledge_templates_dir = knowledge_starter_dir
