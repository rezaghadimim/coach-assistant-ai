"""Remote reranker client for a Cohere/Jina-style OpenAI-adjacent POST /rerank.

Distinct from ``app/core/rerank_tei.py`` (vanilla Hugging Face TEI's
``{"query", "texts"}`` schema, no auth). This server instead expects
``{"model", "query", "documents"}`` and a Bearer token, returning
``{"results": [{"index", "relevance_score"}, ...]}``.
"""

from __future__ import annotations

import httpx


def rerank(
    query: str,
    documents: list[str],
    *,
    base_url: str,
    model: str,
    timeout: float,
    api_key: str = "",
) -> list[float]:
    """Return relevance scores aligned with *documents* input order."""
    if not documents:
        return []

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    response = httpx.post(
        f"{base_url.rstrip('/')}/rerank",
        json={"model": model, "query": query, "documents": documents},
        timeout=timeout,
        headers=headers,
    )
    response.raise_for_status()
    payload = response.json()

    scores = [0.0] * len(documents)
    for item in payload["results"]:
        scores[item["index"]] = float(item["relevance_score"])
    return scores
