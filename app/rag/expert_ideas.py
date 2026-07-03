"""Deterministic post-answer "expert ideas" built from retrieved chunks.

After the assistant answers, we attach a short section that quotes what each
stored expert actually said about the situation — one idea per person, with
the source title and, when the source is a video, the timestamp range and a
link that jumps to that moment. The section is assembled verbatim from
retrieval results (never by the LLM), so every attribution is real.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from app.rag.retriever import CoachRetrievalResult, RetrievedChunk
from app.rag.transcript import format_timestamp

DEFAULT_MAX_IDEAS = 4
DEFAULT_EXCERPT_WORDS = 60

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}


@dataclass(frozen=True)
class ExpertIdea:
    """One attributed idea from a stored expert source."""

    person_name: str
    source_title: str
    excerpt: str
    start_sec: float | None = None
    end_sec: float | None = None
    timestamp: str = ""
    source_uri: str | None = None
    video_url: str | None = None
    score: float = 0.0


def timestamped_media_url(uri: str | None, start_sec: float | None) -> str | None:
    """Return a web URL that opens the source at *start_sec*, when possible.

    YouTube links get a ``t=<seconds>`` query parameter; other http(s) links
    get a media-fragment anchor (``#t=<seconds>``). Non-web URIs (local file
    paths) return None — the timestamp is still shown as text.
    """
    if not uri:
        return None
    parsed = urlparse(uri)
    if parsed.scheme not in {"http", "https"}:
        return None
    if start_sec is None or start_sec <= 0:
        return uri
    seconds = int(start_sec)
    if parsed.hostname in _YOUTUBE_HOSTS:
        separator = "&" if parsed.query else "?"
        return f"{uri}{separator}t={seconds}"
    return f"{uri}#t={seconds}"


def _excerpt(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]) + "…"


def build_expert_ideas(
    result: CoachRetrievalResult,
    *,
    max_ideas: int = DEFAULT_MAX_IDEAS,
    excerpt_words: int = DEFAULT_EXCERPT_WORDS,
) -> list[ExpertIdea]:
    """Build one attributed idea per expert from two-phase retrieval results.

    Expert chunks are already relevance-ordered and diversified across
    collections; we keep the best chunk per person so the section reads as
    "Professor A suggests X, Professor B suggests Y".
    """
    candidates: list[RetrievedChunk] = list(result.expert_chunks)
    if not candidates:
        candidates = [
            chunk for chunk in result.problem_chunks
            if chunk.person_name and chunk.corpus == "collection"
        ]

    ideas: list[ExpertIdea] = []
    seen_people: set[str] = set()
    for chunk in candidates:
        if not chunk.person_name:
            continue
        person_key = chunk.person_name.strip().lower()
        if person_key in seen_people:
            continue
        seen_people.add(person_key)

        timestamp = ""
        start_sec = end_sec = None
        if chunk.has_timing:
            start_sec, end_sec = chunk.start_sec, chunk.end_sec
            timestamp = f"{format_timestamp(start_sec)}–{format_timestamp(end_sec)}"

        ideas.append(
            ExpertIdea(
                person_name=chunk.person_name,
                source_title=chunk.source_title or "",
                excerpt=_excerpt(chunk.text, excerpt_words),
                start_sec=start_sec,
                end_sec=end_sec,
                timestamp=timestamp,
                source_uri=chunk.source_uri,
                video_url=timestamped_media_url(chunk.source_uri, start_sec),
                score=chunk.score,
            )
        )
        if len(ideas) >= max_ideas:
            break
    return ideas


def format_expert_ideas_markdown(ideas: list[ExpertIdea]) -> str:
    """Render the attached ideas section shown after the assistant's answer."""
    if not ideas:
        return ""

    lines = ["---", "**Ideas from your knowledge base**", ""]
    for idea in ideas:
        source = f' — "{idea.source_title}"' if idea.source_title else ""
        location = ""
        if idea.timestamp and idea.video_url:
            location = f" (video {idea.timestamp} — [watch]({idea.video_url}))"
        elif idea.timestamp:
            location = f" (video {idea.timestamp})"
        lines.append(f"- **{idea.person_name}**{source}{location}: {idea.excerpt}")
    return "\n".join(lines)
