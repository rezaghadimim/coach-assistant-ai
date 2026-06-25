"""Document ingestion endpoint for local RAG index."""

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.core.knowledge_paths import knowledge_ingest_summary
from app.models.schemas import IngestRequest, IngestResponse
from app.rag.retriever import ingest_and_index_knowledge

router = APIRouter()


@router.post("/ingest", response_model=IngestResponse)
async def ingest(request: IngestRequest) -> IngestResponse:
    """Ingest and index documents from starter + private knowledge directories."""
    chunk_size = request.chunk_size or settings.rag_chunk_size
    chunk_overlap = request.chunk_overlap or settings.rag_chunk_overlap

    try:
        from app.core.embeddings import probe_embed_model
        use_embed = settings.rag_backend == "embedding" or (
            settings.rag_backend == "auto" and probe_embed_model(corpus="framework")
        )
        documents_indexed, chunks_indexed = ingest_and_index_knowledge(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            embed=use_embed,
            cache_path=settings.rag_index_cache_path if use_embed else None,
            include_collections=True,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (NotADirectoryError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to ingest documents") from exc

    return IngestResponse(
        docs_dir=knowledge_ingest_summary(),
        starter_dir=settings.rag_knowledge_starter_dir,
        private_dir=settings.rag_knowledge_private_dir,
        documents_indexed=documents_indexed,
        chunks_indexed=chunks_indexed,
    )
