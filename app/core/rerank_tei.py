"""Remote reranker client for a Hugging Face Text-Embeddings-Inference (TEI) server.

TEI serves one fixed cross-encoder model per deployment (started with e.g.
``--model-id BAAI/bge-reranker-base``), so unlike the local fastembed path the
model name is not part of the request.
"""

from __future__ import annotations

import httpx


def rerank(
    query: str,
    documents: list[str],
    *,
    base_url: str,
    timeout: float,
) -> list[float]:
    """Return TEI relevance scores aligned with *documents* input order.

    Scores are sigmoid-normalized (0, 1) by TEI itself (``raw_scores=False``),
    matching the scale produced by the local fastembed path.
    """
    if not documents:
        return []

    response = httpx.post(
        f"{base_url.rstrip('/')}/rerank",
        json={"query": query, "texts": documents, "raw_scores": False, "truncate": True},
        timeout=timeout,
    )
    response.raise_for_status()
    results = response.json()

    scores = [0.0] * len(documents)
    for item in results:
        scores[item["index"]] = float(item["score"])
    return scores
