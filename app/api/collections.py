"""Knowledge collection API endpoints."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.core.embed_providers import embed_profile_for_corpus
from app.core.embeddings import probe_embed_model
from app.knowledge.ingest import ingest_collection_chunks_from_disk
from app.knowledge.jobs import process_pending_sources
from app.knowledge.store import KnowledgeStore
from app.models.schemas import (
    CollectionCreateRequest,
    CollectionReindexResponse,
    CollectionResponse,
    ProcessJobsResponse,
    SourceCreateRequest,
    SourceResponse,
)
from app.rag.retriever import index_chunks, ingest_and_index_knowledge

router = APIRouter()
store = KnowledgeStore(settings.memory_db_path)


def _collection_response(row: dict) -> CollectionResponse:
    default_profile = embed_profile_for_corpus("collection")
    return CollectionResponse(
        id=row["id"],
        slug=row["slug"],
        person_name=row["person_name"],
        title=row["title"],
        description=row.get("description") or "",
        embed_provider=row.get("embed_provider") or default_profile.provider,
        embed_model=row.get("embed_model") or default_profile.model,
        source_count=int(row.get("source_count") or 0),
        chunk_count=int(row.get("chunk_count") or 0),
        created_at=row.get("created_at"),
    )


def _source_response(row: dict) -> SourceResponse:
    return SourceResponse(
        id=row["id"],
        collection_id=row["collection_id"],
        title=row["title"],
        source_type=row["source_type"],
        uri=row.get("uri") or "",
        duration_sec=row.get("duration_sec"),
        status=row["status"],
        error_message=row.get("error_message"),
        created_at=row.get("created_at"),
    )


@router.get("/collections", response_model=list[CollectionResponse])
async def list_collections() -> list[CollectionResponse]:
    return [_collection_response(row) for row in store.list_collections()]


@router.post("/collections", response_model=CollectionResponse)
async def create_collection(request: CollectionCreateRequest) -> CollectionResponse:
    if store.get_collection(request.slug):
        raise HTTPException(status_code=409, detail=f"Collection already exists: {request.slug}")

    default_profile = embed_profile_for_corpus("collection")
    payload = {
        "slug": request.slug,
        "person_name": request.person_name,
        "title": request.title,
        "description": request.description,
        "embed_provider": request.embed_provider or default_profile.provider,
        "embed_model": request.embed_model or default_profile.model,
    }
    store.write_collection_json(request.slug, settings.rag_collections_dir, payload)
    row = store.create_collection(
        slug=request.slug,
        person_name=request.person_name,
        title=request.title,
        description=request.description,
        embed_provider=payload["embed_provider"],
        embed_model=payload["embed_model"],
    )
    return _collection_response(row)


@router.post("/collections/{collection_id}/sources", response_model=SourceResponse)
async def add_source(collection_id: str, request: SourceCreateRequest) -> SourceResponse:
    collection = store.get_collection(collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    status = "ready" if request.source_type == "transcript" else "pending"
    row = store.create_source(
        collection["id"],
        title=request.title,
        source_type=request.source_type,
        uri=request.uri,
        status=status,
        source_id=request.source_id,
    )

    if request.source_id:
        collections_root = Path(settings.rag_collections_dir).resolve()
        source_dir = (
            collections_root / collection["slug"] / "sources" / request.source_id
        )
        # Defense in depth: the schema already restricts source_id to a slug,
        # but re-verify the resolved path stays inside the collections dir
        # before any mkdir/write so a traversal can never escape it.
        if not source_dir.resolve().is_relative_to(collections_root):
            raise HTTPException(status_code=400, detail="Invalid source_id")
        source_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "title": request.title,
            "source_type": request.source_type,
            "uri": request.uri,
            "source_id": request.source_id,
        }
        (source_dir / "meta.json").write_text(
            json.dumps(meta, indent=2),
            encoding="utf-8",
        )

    return _source_response(row)


@router.get("/collections/{collection_id}/sources/{source_id}", response_model=SourceResponse)
async def get_source(collection_id: str, source_id: str) -> SourceResponse:
    collection = store.get_collection(collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    row = store.get_source(source_id)
    if row is None or row["collection_id"] != collection["id"]:
        raise HTTPException(status_code=404, detail="Source not found")
    return _source_response(row)


@router.post("/collections/{collection_id}/reindex", response_model=CollectionReindexResponse)
async def reindex_collection(collection_id: str) -> CollectionReindexResponse:
    collection = store.get_collection(collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    process_pending_sources(knowledge_store=store)
    all_chunks = ingest_collection_chunks_from_disk(
        knowledge_store=store,
        chunk_size=settings.rag_chunk_size,
        chunk_overlap=settings.rag_chunk_overlap,
    )
    collection_chunks = [
        chunk for chunk in all_chunks if chunk.collection_id == collection["id"]
    ]
    # Rebuild the full collection index so removed sources disappear.
    use_embed = probe_embed_model(corpus="collection") or probe_embed_model(corpus="framework")
    index_chunks(
        all_chunks,
        reset=True,
        embed=use_embed,
        cache_path=settings.rag_index_cache_path if use_embed else None,
        corpus="collection",
    )
    return CollectionReindexResponse(
        collection_id=collection["id"],
        sources_indexed=len(store.list_sources(collection["id"])),
        chunks_indexed=len(collection_chunks),
    )


@router.post("/collections/process-jobs", response_model=ProcessJobsResponse)
async def run_collection_jobs() -> ProcessJobsResponse:
    processed = process_pending_sources(knowledge_store=store)
    if processed:
        ingest_and_index_knowledge(
            chunk_size=settings.rag_chunk_size,
            chunk_overlap=settings.rag_chunk_overlap,
            embed=probe_embed_model(corpus="framework"),
            cache_path=settings.rag_index_cache_path,
            include_collections=True,
        )
    return ProcessJobsResponse(processed_source_ids=processed)
