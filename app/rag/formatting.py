"""Citation and prompt formatting for retrieved coaching chunks."""

from __future__ import annotations

import os

from app.rag.retriever import CoachRetrievalResult, RetrievedChunk


def format_retrieval_context(chunks: list[RetrievedChunk]) -> str:
    """Format retrieved chunks for inclusion in a system prompt."""
    if not chunks:
        return ""

    lines = [
        "## Relevant Coaching Knowledge",
        (
            "Use ONLY the passages below to answer factual questions about "
            "coaching methods, frameworks, or techniques. "
            "If the answer is not contained in these passages, say you do not "
            "have that in your knowledge base and continue from general coaching "
            "principles — never invent sources, studies, statistics, or quotes."
        ),
        "",
    ]
    for index, chunk in enumerate(chunks, start=1):
        source_name = os.path.basename(chunk.source_path)
        lines.append(f"[{index}] Source: {source_name} (score={chunk.score:.2f})")
        lines.append(chunk.text)
        lines.append("")
    return "\n".join(lines).strip()


def format_coach_retrieval_context(result: CoachRetrievalResult) -> str:
    """Format two-phase retrieval for chat system prompts."""
    if not result.problem_chunks and not result.expert_chunks:
        return ""

    sections: list[str] = []
    if result.problem_chunks:
        lines = [
            "## Relevant Coaching Knowledge (situation)",
            (
                "Use these passages to understand the coaching situation. "
                "When a passage names an expert and guide, preserve that attribution "
                "in your reply (person, guide title, timestamp if shown). "
                "Do not invent facts beyond what is written here."
            ),
            "",
        ]
        for index, chunk in enumerate(result.problem_chunks, start=1):
            lines.append(_format_chunk_citation(index, chunk))
            lines.append(chunk.text)
            lines.append("")
        sections.append("\n".join(lines).strip())

    if result.expert_chunks:
        lines = [
            "## Expert Perspectives (stored solutions)",
            (
                "Present each expert separately. Compare where they agree or differ. "
                "Do not merge into one anonymous voice. "
                "Structure your reply as: (1) brief coaching suggestion, "
                "(2) what each expert recommends with attribution, "
                "(3) comparison when relevant."
            ),
            "",
        ]
        for chunk in result.expert_chunks:
            header = _format_expert_header(chunk)
            lines.append(header)
            lines.append(chunk.text)
            lines.append("")
        sections.append("\n".join(lines).strip())

    return "\n\n".join(sections)


def _format_chunk_citation(index: int, chunk: RetrievedChunk) -> str:
    source_name = os.path.basename(chunk.source_path)
    if chunk.person_name and chunk.source_title:
        from app.rag.transcript import format_timestamp

        ts = ""
        if chunk.has_timing:
            ts = f" ({format_timestamp(chunk.start_sec)}–{format_timestamp(chunk.end_sec)})"
        return (
            f"[{index}] Expert: {chunk.person_name} — "
            f"\"{chunk.source_title}\"{ts} (score={chunk.score:.2f})"
        )
    return f"[{index}] Source: {source_name} (score={chunk.score:.2f})"


def _format_expert_header(chunk: RetrievedChunk) -> str:
    from app.rag.transcript import format_timestamp

    person = chunk.person_name or "Expert"
    title = chunk.source_title or os.path.basename(chunk.source_path)
    ts = ""
    if chunk.has_timing:
        ts = f" ({format_timestamp(chunk.start_sec)}–{format_timestamp(chunk.end_sec)})"
    return f"### {person} — \"{title}\"{ts}"
