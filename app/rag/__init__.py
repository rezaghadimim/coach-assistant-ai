"""RAG utilities for document ingestion and retrieval."""

from .ingest import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    DocumentChunk,
    discover_documents,
    ingest_documents_from_dir,
    read_document,
)

__all__ = [
    "DEFAULT_CHUNK_OVERLAP",
    "DEFAULT_CHUNK_SIZE",
    "DocumentChunk",
    "discover_documents",
    "ingest_documents_from_dir",
    "read_document",
]
