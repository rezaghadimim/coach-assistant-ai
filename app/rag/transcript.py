"""SRT/VTT/JSON transcript parsing and time-aware chunking."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.rag.ingest import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE, DocumentChunk, infer_chunk_role

_TIMESTAMP = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*"
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)
_VTT_HEADER = re.compile(r"^WEBVTT", re.IGNORECASE)


@dataclass(frozen=True)
class TranscriptSegment:
  """One timed caption segment."""

  text: str
  start_sec: float
  end_sec: float


def parse_timestamp_to_seconds(hours: str, minutes: str, seconds: str, millis: str) -> float:
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000.0


def parse_srt_or_vtt(text: str) -> list[TranscriptSegment]:
    """Parse SRT or WebVTT content into timed segments."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    segments: list[TranscriptSegment] = []
    index = 0
    if lines and _VTT_HEADER.match(lines[0].strip()):
        index = 1
        while index < len(lines) and lines[index].strip():
            index += 1

    while index < len(lines):
        line = lines[index].strip()
        index += 1
        if not line:
            continue
        if line.isdigit():
            if index >= len(lines):
                break
            line = lines[index].strip()
            index += 1
        match = _TIMESTAMP.search(line)
        if not match:
            continue
        start = parse_timestamp_to_seconds(*match.groups()[:4])
        end = parse_timestamp_to_seconds(*match.groups()[4:])
        body_lines: list[str] = []
        while index < len(lines) and lines[index].strip():
            body_lines.append(lines[index].strip())
            index += 1
        body = re.sub(r"<[^>]+>", "", " ".join(body_lines)).strip()
        if body:
            segments.append(TranscriptSegment(text=body, start_sec=start, end_sec=end))
    return segments


_JSON_TEXT_KEYS = ("text", "message", "content")
_JSON_START_KEYS = ("start_sec", "start", "time", "timestamp", "offset")
_JSON_END_KEYS = ("end_sec", "end")


def _segment_from_json_item(item: Any) -> TranscriptSegment | None:
    if not isinstance(item, dict):
        return None
    text = next(
        (str(item[key]).strip() for key in _JSON_TEXT_KEYS if item.get(key)),
        "",
    )
    if not text:
        return None
    start = next(
        (float(item[key]) for key in _JSON_START_KEYS if item.get(key) is not None),
        0.0,
    )
    end = next(
        (float(item[key]) for key in _JSON_END_KEYS if item.get(key) is not None),
        start,
    )
    return TranscriptSegment(text=text, start_sec=start, end_sec=end)


def parse_json_transcript(text: str) -> list[TranscriptSegment]:
    """Parse a JSON transcript into timed segments.

    Accepts a bare list of segment objects, or an object with a ``segments``
    or ``messages`` list (Whisper-style output and chat-message exports).
    Each item carries its text under ``text``/``message``/``content`` and its
    timing under ``start``/``end`` (or ``start_sec``/``end_sec``/``time``/
    ``timestamp``), expressed in seconds.
    """
    data = json.loads(text)
    if isinstance(data, dict):
        items = data.get("segments") or data.get("messages") or []
    elif isinstance(data, list):
        items = data
    else:
        items = []
    segments = (_segment_from_json_item(item) for item in items)
    return [segment for segment in segments if segment is not None]


def read_transcript_file(path: Path) -> list[TranscriptSegment]:
    suffix = path.suffix.lower()
    if suffix in {".srt", ".vtt"}:
        return parse_srt_or_vtt(path.read_text(encoding="utf-8"))
    if suffix == ".json":
        return parse_json_transcript(path.read_text(encoding="utf-8"))
    if suffix in {".txt", ".md"}:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return []
        return [TranscriptSegment(text=text, start_sec=0.0, end_sec=0.0)]
    raise ValueError(f"Unsupported transcript format: {suffix}")


def build_transcript_chunks(
    segments: list[TranscriptSegment],
    *,
    source_path: str,
    chunk_id_prefix: str,
    collection_id: str,
    collection_slug: str,
    person_name: str,
    source_title: str,
    embed_profile_id: str,
    source_uri: str | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[DocumentChunk]:
    """Group transcript segments into token windows with timestamp metadata."""
    if not segments:
        return []

    chunks: list[DocumentChunk] = []
    buffer_text: list[str] = []
    buffer_tokens = 0
    start_sec = segments[0].start_sec
    end_sec = segments[0].end_sec
    chunk_index = 0
    step = max(chunk_size - chunk_overlap, 1)

    def flush() -> None:
        nonlocal chunk_index, buffer_text, buffer_tokens, start_sec, end_sec
        if not buffer_text:
            return
        text = " ".join(buffer_text).strip()
        if not text:
            buffer_text = []
            buffer_tokens = 0
            return
        chunks.append(
            DocumentChunk(
                chunk_id=f"{chunk_id_prefix}:{chunk_index}",
                source_path=source_path,
                text=text,
                start_token=0,
                end_token=len(text.split()),
                collection_id=collection_id,
                collection_slug=collection_slug,
                person_name=person_name,
                source_title=source_title,
                source_uri=source_uri,
                start_sec=start_sec,
                end_sec=end_sec,
                corpus="collection",
                embed_profile_id=embed_profile_id,
                chunk_role=infer_chunk_role(text),
            )
        )
        chunk_index += 1
        buffer_text = []
        buffer_tokens = 0

    for segment in segments:
        words = segment.text.split()
        if not words:
            continue
        if not buffer_text:
            start_sec = segment.start_sec
        for word in words:
            buffer_text.append(word)
            buffer_tokens += 1
            end_sec = segment.end_sec
            if buffer_tokens >= chunk_size:
                flush()
                if buffer_text:
                    overlap_words = buffer_text[-chunk_overlap:] if chunk_overlap else []
                    buffer_text = list(overlap_words)
                    buffer_tokens = len(buffer_text)
                    start_sec = segment.start_sec
    flush()
    return chunks


def format_timestamp(seconds: float | None) -> str:
    if seconds is None:
        return ""
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"
