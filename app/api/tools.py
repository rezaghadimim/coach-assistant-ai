"""Tool routing API — classify messages and manage the routing index."""

from fastapi import APIRouter

from app.core.config import settings
from app.models.schemas import (
    ToolClassifyRequest,
    ToolClassifyResponse,
    ToolMatchItem,
    ToolReindexResponse,
)

router = APIRouter()


@router.post("/tools/classify", response_model=ToolClassifyResponse)
async def classify_tool_endpoint(request: ToolClassifyRequest) -> ToolClassifyResponse:
    """Classify a message into the best-matching tool.

    Returns the top match (if confident) and top-3 candidates for debugging.
    Use this endpoint to inspect routing decisions and tune thresholds.
    """
    from app.core.tool_router import classify_tool, top_n_tools

    match = classify_tool(request.message)
    top = top_n_tools(request.message, n=3)

    return ToolClassifyResponse(
        message=request.message,
        tool=match.tool if match else None,
        score=match.score if match else None,
        hint=match.hint if match else None,
        backend=match.backend if match else None,
        top_n=[
            ToolMatchItem(
                tool=m.tool,
                score=m.score,
                hint=m.hint,
                utterance=m.utterance,
            )
            for m in top
        ],
        deferred=match is None,
    )


@router.post("/tools/reindex", response_model=ToolReindexResponse)
async def reindex_tool_router() -> ToolReindexResponse:
    """Rebuild the tool routing index from ``routing.jsonl``.

    Call after editing ``docs/tool-knowledge/examples/routing.jsonl`` to pick
    up new examples without restarting the server.
    """
    from app.core.tool_router import build_index, reset_index

    reset_index()
    count = build_index(force=True)

    return ToolReindexResponse(
        examples_indexed=count,
        backend=settings.tool_router_backend,
    )
