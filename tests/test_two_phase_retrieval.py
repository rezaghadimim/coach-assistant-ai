"""Tests for two-phase coach retrieval."""

from unittest.mock import patch

from app.rag.ingest import DocumentChunk
from app.rag.retriever import (
    CoachRetrievalResult,
    clear_index,
    diversify_by_collection,
    format_coach_retrieval_context,
    index_chunks,
    retrieve_coach_context,
    RetrievedChunk,
    _build_solution_query,
)


def _collection_chunk(
    chunk_id: str,
    text: str,
    *,
    person: str,
    collection_id: str,
    role: str = "solution",
) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        source_path=f"/data/{chunk_id}.vtt",
        text=text,
        start_token=0,
        end_token=len(text.split()),
        collection_id=collection_id,
        collection_slug=person.lower(),
        person_name=person,
        source_title=f"{person} guide",
        start_sec=10.0,
        end_sec=20.0,
        corpus="collection",
        embed_profile_id="openrouter/text-embedding-3-small",
        chunk_role=role,  # type: ignore[arg-type]
    )


def test_build_solution_query_includes_problem_context() -> None:
    problem = [
        RetrievedChunk(
            chunk_id="p1",
            source_path="grow.md",
            text="Clients who cancel may be avoiding accountability.",
            score=0.9,
        )
    ]
    query = _build_solution_query("client keeps canceling", problem)
    assert "practical coaching solutions" in query
    assert "cancel" in query.lower()


def test_diversify_by_collection_returns_multiple_people() -> None:
    chunks = [
        RetrievedChunk("a", "s1", "text a", 0.9, collection_id="c1", person_name="A"),
        RetrievedChunk("b", "s2", "text b", 0.85, collection_id="c1", person_name="A"),
        RetrievedChunk("c", "s3", "text c", 0.8, collection_id="c2", person_name="B"),
    ]
    diversified = diversify_by_collection(chunks, min_collections=2, max_per_collection=1)
    people = {chunk.person_name for chunk in diversified}
    assert people == {"A", "B"}


def test_format_coach_retrieval_context_sections() -> None:
    result = CoachRetrievalResult(
        problem_chunks=[
            RetrievedChunk("p", "grow.md", "framework text", 0.8),
        ],
        expert_chunks=[
            RetrievedChunk(
                "e",
                "guide.vtt",
                "expert solution text",
                0.7,
                person_name="Jane Doe",
                source_title="Resistance",
                start_sec=8.0,
                end_sec=45.0,
            )
        ],
    )
    text = format_coach_retrieval_context(result)
    assert "Relevant Coaching Knowledge (situation)" in text
    assert "Expert Perspectives" in text
    assert "Jane Doe" in text


def test_retrieve_coach_context_uses_collection_index() -> None:
    clear_index()
    chunks = [
        _collection_chunk("jane:0", "how to handle session cancellation resistance", person="Jane", collection_id="c1"),
        _collection_chunk("john:0", "practical solution use motivational interviewing reframe", person="John", collection_id="c2"),
    ]
    index_chunks(chunks, embed=False, corpus="collection", reset=True)

    with patch("app.core.config.settings.rag_two_phase_enabled", True):
        with patch("app.core.config.settings.rag_rerank_enabled", False):
            result = retrieve_coach_context("client keeps canceling sessions")
    assert isinstance(result, CoachRetrievalResult)


def test_small_collection_phase2_reranks_even_when_fewer_than_top_k() -> None:
    clear_index()
    chunks = [
        _collection_chunk(
            "whitmore:0",
            "GROW model Goal Reality Options Will structure every coaching session",
            person="Sir John Whitmore",
            collection_id="c-grow",
        ),
        _collection_chunk(
            "goldsmith:0",
            "feedforward practical coaching steps for future behavior change",
            person="Marshall Goldsmith",
            collection_id="c-feed",
        ),
    ]
    index_chunks(chunks, embed=False, corpus="collection", reset=True)

    with patch("app.core.config.settings.rag_two_phase_enabled", True):
        with patch("app.core.config.settings.rag_rerank_enabled", True):
            with patch("app.rag.reranker.rerank") as mock_rerank:
                mock_rerank.side_effect = lambda query, candidates, top_k: candidates[:top_k]
                result = retrieve_coach_context("How do I structure a session using GROW?")

    assert result.expert_chunks
    mock_rerank.assert_called()
