"""Load collection transcripts from disk into DocumentChunk objects."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.embed_providers import embed_profile_for_corpus, get_embed_provider
from app.knowledge.store import KnowledgeStore
from app.rag.ingest import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE, DocumentChunk
from app.rag.transcript import build_transcript_chunks, read_transcript_file

logger = logging.getLogger(__name__)

_MEDIA_EXTENSIONS = {".mp4", ".webm", ".mp3", ".m4a", ".wav", ".mkv"}


def _load_collection_meta(collection_dir: Path) -> dict[str, Any]:
    meta_path = collection_dir / "collection.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    slug = collection_dir.name
    return {
        "slug": slug,
        "person_name": slug.replace("-", " ").title(),
        "title": slug.replace("-", " ").title(),
        "description": "",
    }


def _source_meta(source_dir: Path) -> dict[str, Any]:
    meta_path = source_dir / "meta.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    return {"title": source_dir.name.replace("-", " ").title(), "source_type": "transcript"}


def ingest_collection_chunks_from_disk(
    collections_dir: str | None = None,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    knowledge_store: KnowledgeStore | None = None,
) -> list[DocumentChunk]:
    """Discover filesystem collections and return transcript chunks."""
    root = Path(collections_dir or settings.rag_collections_dir).expanduser().resolve()
    if not root.exists():
        return []

    store = knowledge_store or KnowledgeStore(settings.memory_db_path)
    all_chunks: list[DocumentChunk] = []
    collection_profile = embed_profile_for_corpus("collection")

    for collection_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        meta = _load_collection_meta(collection_dir)
        slug = meta.get("slug", collection_dir.name)
        person_name = meta.get("person_name", slug)
        title = meta.get("title", slug)
        description = meta.get("description", "")
        embed_provider = meta.get("embed_provider", settings.rag_collection_embed_provider)
        embed_model = meta.get("embed_model", settings.rag_collection_embed_model)

        existing = store.get_collection(slug)
        if existing is None:
            collection = store.create_collection(
                slug=slug,
                person_name=person_name,
                title=title,
                description=description,
                embed_provider=embed_provider,
                embed_model=embed_model,
            )
        else:
            collection = existing
        collection_id = collection["id"]

        profile = embed_profile_for_corpus("collection")
        if embed_model:
            from app.core.embed_providers.types import EmbedProfile

            profile = EmbedProfile(
                provider=embed_provider,  # type: ignore[arg-type]
                model=embed_model,
                dimensions=profile.dimensions,
                use_e5_prefix=False,
            )
        embed_profile_id = profile.profile_id

        sources_dir = collection_dir / "sources"
        if not sources_dir.exists():
            continue

        for source_dir in sorted(path for path in sources_dir.iterdir() if path.is_dir()):
            source_meta = _source_meta(source_dir)
            source_title = source_meta.get("title", source_dir.name)
            source_type = source_meta.get("source_type", "transcript")
            uri = source_meta.get("uri", "")

            transcript_files = [
                path
                for path in source_dir.iterdir()
                if path.is_file() and path.suffix.lower() in {".srt", ".vtt", ".txt", ".md"}
            ]
            media_files = [
                path
                for path in source_dir.iterdir()
                if path.is_file() and path.suffix.lower() in _MEDIA_EXTENSIONS
            ]

            if not transcript_files and media_files:
                _register_pending_media_source(
                    store,
                    collection_id=collection_id,
                    source_dir=source_dir,
                    source_title=source_title,
                    source_type=source_type or "local_media",
                    uri=uri or str(media_files[0]),
                )
                continue

            if not transcript_files:
                continue

            source_id = source_meta.get("source_id") or source_dir.name
            existing_source = next(
                (
                    item
                    for item in store.list_sources(collection_id)
                    if item["title"] == source_title or item["id"] == source_id
                ),
                None,
            )
            if existing_source is None:
                source = store.create_source(
                    collection_id,
                    title=source_title,
                    source_type=source_type,
                    uri=uri or str(transcript_files[0]),
                    status="ready",
                    source_id=source_id if source_id else None,
                )
            else:
                source = existing_source
                store.update_source_status(source["id"], status="ready")

            source_chunks: list[DocumentChunk] = []
            for transcript_path in transcript_files:
                segments = read_transcript_file(transcript_path)
                source_chunks.extend(
                    build_transcript_chunks(
                        segments,
                        source_path=str(transcript_path),
                        chunk_id_prefix=f"{slug}/{source['id']}",
                        collection_id=collection_id,
                        collection_slug=slug,
                        person_name=person_name,
                        source_title=source_title,
                        embed_profile_id=embed_profile_id,
                        chunk_size=chunk_size,
                        chunk_overlap=chunk_overlap,
                    )
                )

            if source_chunks:
                store.replace_chunks_for_source(
                    collection_id,
                    source["id"],
                    [
                        {
                            "chunk_id": chunk.chunk_id,
                            "text": chunk.text,
                            "start_sec": chunk.start_sec,
                            "end_sec": chunk.end_sec,
                            "embed_profile_id": chunk.embed_profile_id,
                        }
                        for chunk in source_chunks
                    ],
                )
            all_chunks.extend(source_chunks)

    return all_chunks


def _register_pending_media_source(
    store: KnowledgeStore,
    *,
    collection_id: str,
    source_dir: Path,
    source_title: str,
    source_type: str,
    uri: str,
) -> None:
    existing = next(
        (item for item in store.list_sources(collection_id) if item["title"] == source_title),
        None,
    )
    if existing is None:
        store.create_source(
            collection_id,
            title=source_title,
            source_type=source_type,
            uri=uri,
            status="pending",
            source_id=source_dir.name,
        )


def embed_collection_chunks(
    chunks: list[DocumentChunk],
    *,
    cache_path: str | None = None,
) -> dict[str, list[float]]:
    """Batch-embed collection chunks using the collection embed provider."""
    import hashlib
    import json
    from pathlib import Path

    from app.core.embed_providers import embed_profile_for_corpus, get_embed_provider

    if not chunks:
        return {}

    profile = embed_profile_for_corpus("collection")
    provider = get_embed_provider(profile)
    cache: dict[str, list[float]] = {}
    path = Path(cache_path) if cache_path else None
    if path and path.exists():
        try:
            cache = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    pending_texts: list[str] = []
    pending_keys: list[str] = []
    for chunk in chunks:
        text_hash = hashlib.sha256(chunk.text.encode()).hexdigest()[:16]
        key = f"{chunk.embed_profile_id}::{chunk.chunk_id}::{text_hash}"
        if key in cache:
            continue
        pending_keys.append(key)
        pending_texts.append(chunk.text)

    if pending_texts:
        logger.info(
            "collection embed: embedding %d new chunks via %s",
            len(pending_texts),
            profile.profile_id,
        )
        vectors = provider.embed_passages(pending_texts)
        for key, vector in zip(pending_keys, vectors):
            cache[key] = vector
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(cache), encoding="utf-8")

    return cache
