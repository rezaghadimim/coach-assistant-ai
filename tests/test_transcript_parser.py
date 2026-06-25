"""Tests for SRT/VTT transcript parsing."""

from app.rag.transcript import (
    build_transcript_chunks,
    format_timestamp,
    parse_srt_or_vtt,
)


def test_parse_srt_segments() -> None:
    content = """1
00:00:01,000 --> 00:00:04,000
First line of advice.

2
00:00:05,000 --> 00:00:08,500
Second line about solutions.
"""
    segments = parse_srt_or_vtt(content)
    assert len(segments) == 2
    assert segments[0].text == "First line of advice."
    assert segments[0].start_sec == 1.0
    assert segments[1].end_sec == 8.5


def test_build_transcript_chunks_preserves_timestamps() -> None:
    content = """1
00:00:10,000 --> 00:00:15,000
How to handle resistance when a client keeps canceling sessions.
"""
    segments = parse_srt_or_vtt(content)
    chunks = build_transcript_chunks(
        segments,
        source_path="/tmp/guide.vtt",
        chunk_id_prefix="jane/guide-1",
        collection_id="cid",
        collection_slug="jane",
        person_name="Jane Doe",
        source_title="Handling resistance",
        embed_profile_id="openrouter/text-embedding-3-small",
        chunk_size=20,
        chunk_overlap=5,
    )
    assert chunks
    assert chunks[0].person_name == "Jane Doe"
    assert chunks[0].start_sec == 10.0
    assert chunks[0].corpus == "collection"


def test_format_timestamp() -> None:
    assert format_timestamp(65) == "01:05"
    assert format_timestamp(3661) == "01:01:01"
