"""Document ingestion endpoint for local RAG index."""

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.models.schemas import IngestRequest, IngestResponse
from app.rag.retriever import ingest_and_index_directory

router = APIRouter()


@router.post("/ingest", response_model=IngestResponse)
async def ingest(request: IngestRequest) -> IngestResponse:
    """Ingest and index documents from a local directory."""
    docs_dir = request.docs_dir or settings.rag_docs_dir
    chunk_size = request.chunk_size or settings.rag_chunk_size
    chunk_overlap = request.chunk_overlap or settings.rag_chunk_overlap

    try:
        documents_indexed, chunks_indexed = ingest_and_index_directory(
            docs_dir,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return IngestResponse(
        docs_dir=docs_dir,
        documents_indexed=documents_indexed,
        chunks_indexed=chunks_indexed,
    )
