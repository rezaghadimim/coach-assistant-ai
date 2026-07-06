"""Background media processing for knowledge collections."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from app.core.config import settings
from app.knowledge.store import KnowledgeStore

logger = logging.getLogger(__name__)

_TRANSCRIPT_NAMES = ("transcript.txt", "transcript.vtt", "transcript.srt")

# English caption variants to accept, in preference order.
_CAPTION_LANGS = ("en", "en-US", "en-GB")

# Hosts yt-dlp may be pointed at. Caller-supplied URIs otherwise allow SSRF
# (internal/metadata services) and option injection into the yt-dlp argv.
_ALLOWED_VIDEO_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
    }
)


def _validate_video_url(uri: str) -> str:
    """Return ``uri`` if it is an https URL on an allowed video host; raise otherwise."""
    parsed = urlsplit(uri)
    if parsed.scheme != "https":
        raise ValueError(f"Rejected video URI (https required): {uri!r}")
    if parsed.hostname not in _ALLOWED_VIDEO_HOSTS:
        raise ValueError(f"Rejected video URI (host not allowed): {uri!r}")
    return uri


def _validate_local_media_path(uri: str) -> Path:
    """Resolve ``uri`` and require containment under ``settings.media_root``."""
    media_root = Path(settings.media_root).resolve()
    media_path = Path(uri).resolve()
    if not media_path.is_relative_to(media_root):
        raise ValueError(
            f"Rejected local media path outside media_root ({media_root}): {uri!r}"
        )
    return media_path


def _youtube_video_id(uri: str) -> str:
    """Extract the 11-char video id from a watch / youtu.be / embed / shorts URL."""
    parsed = urlsplit(uri)
    host = parsed.hostname or ""
    if host == "youtu.be":
        vid = parsed.path.lstrip("/").split("/", 1)[0]
    elif parsed.path == "/watch":
        vid = parse_qs(parsed.query).get("v", [""])[0]
    else:
        # /embed/<id>, /shorts/<id>, /live/<id>
        parts = [p for p in parsed.path.split("/") if p]
        vid = parts[1] if len(parts) >= 2 and parts[0] in {"embed", "shorts", "live"} else ""
    if not vid:
        raise ValueError(f"Could not extract a YouTube video id from: {uri!r}")
    return vid


def _caption_ts(seconds: float) -> str:
    """Format seconds as a WebVTT timestamp (HH:MM:SS.mmm)."""
    ms = int(round(max(seconds, 0.0) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _captions_to_vtt(snippets: list[dict]) -> str:
    """Render youtube-transcript-api snippets as a WebVTT document."""
    lines = ["WEBVTT", ""]
    for snip in snippets:
        start = float(snip["start"])
        end = start + float(snip.get("duration", 0.0))
        text = " ".join(snip["text"].split())
        if not text:
            continue
        lines.append(f"{_caption_ts(start)} --> {_caption_ts(end)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def _fetch_youtube_captions(video_id: str, transcript_path: Path) -> bool:
    """Write English captions to ``transcript_path`` as VTT. Return False if none.

    Uses youtube-transcript-api (a separate timedtext endpoint); yt-dlp caption
    download is blocked by YouTube's PO-token requirement as of 2025.
    """
    try:
        from youtube_transcript_api import (
            NoTranscriptFound,
            TranscriptsDisabled,
            YouTubeTranscriptApi,
        )
    except ImportError as exc:
        raise RuntimeError(
            "youtube-transcript-api is required for caption fetching. "
            "Install with: pip install youtube-transcript-api"
        ) from exc

    try:
        fetched = YouTubeTranscriptApi().fetch(video_id, languages=list(_CAPTION_LANGS))
    except (TranscriptsDisabled, NoTranscriptFound):
        return False

    snippets = fetched.to_raw_data()
    if not snippets:
        return False
    transcript_path.write_text(_captions_to_vtt(snippets), encoding="utf-8")
    return True


def process_pending_sources(
    *,
    knowledge_store: KnowledgeStore | None = None,
    collections_dir: str | None = None,
) -> list[str]:
    """Transcribe pending local media and fetch YouTube captions when possible."""
    store = knowledge_store or KnowledgeStore(settings.memory_db_path)
    # When a caller passes an explicit dir (e.g. tests) use it verbatim; otherwise
    # resolve each collection to the root (public or private) that actually holds it.
    explicit_root = Path(collections_dir) if collections_dir is not None else None
    default_root = explicit_root or Path(settings.rag_collections_dir)
    processed: list[str] = []

    for collection in store.list_collections():
        root = explicit_root or _collection_root(collection, default_root)
        for source in store.list_sources(collection["id"]):
            if source["status"] != "pending":
                continue
            try:
                if source["source_type"] == "youtube":
                    _process_youtube_source(store, collection, source, root)
                elif source["source_type"] in {"local_media", "video", "audio"}:
                    _process_local_media_source(store, collection, source, root)
                else:
                    store.update_source_status(
                        source["id"],
                        status="failed",
                        error_message=f"Unsupported source_type: {source['source_type']}",
                    )
                    continue
                processed.append(source["id"])
            except Exception as exc:
                logger.exception("knowledge job failed for source %s", source["id"])
                store.update_source_status(
                    source["id"],
                    status="failed",
                    error_message=str(exc),
                )
    return processed


def _collection_root(collection: dict, default_root: Path) -> Path:
    """Return the collection root (public or private) that holds this collection."""
    from app.core.knowledge_paths import collection_dirs

    slug = collection["slug"]
    for root in collection_dirs():
        if (root / slug).is_dir():
            return root
    return default_root


def _source_directory(collection: dict, source: dict, root: Path) -> Path:
    slug = collection["slug"]
    source_dir = root / slug / "sources" / source["id"]
    source_dir.mkdir(parents=True, exist_ok=True)
    return source_dir


def _process_local_media_source(
    store: KnowledgeStore,
    collection: dict,
    source: dict,
    root: Path,
) -> None:
    media_path = _validate_local_media_path(source["uri"])
    if not media_path.exists():
        raise FileNotFoundError(f"Media file not found: {media_path}")

    source_dir = _source_directory(collection, source, root)
    audio_path = source_dir / "audio.wav"
    _extract_audio(media_path, audio_path)
    transcript_path = source_dir / "transcript.txt"
    _transcribe_audio(audio_path, transcript_path)
    store.update_source_status(source["id"], status="ready", error_message=None)


def _process_youtube_source(
    store: KnowledgeStore,
    collection: dict,
    source: dict,
    root: Path,
) -> None:
    source_dir = _source_directory(collection, source, root)
    url = source["uri"]
    if not url:
        raise ValueError("YouTube source is missing uri")
    url = _validate_video_url(url)
    video_id = _youtube_video_id(url)

    # Prefer captions (fast, no download). Fall back to audio + Whisper only when
    # the video has no captions at all.
    subtitle_path = source_dir / "transcript.vtt"
    if _fetch_youtube_captions(video_id, subtitle_path):
        store.update_source_status(source["id"], status="ready", error_message=None)
        return

    if shutil.which("yt-dlp") is None:
        raise RuntimeError("yt-dlp is not installed (needed to download audio for Whisper)")

    audio_path = source_dir / "audio.wav"
    subprocess.run(
        [
            "yt-dlp",
            "-x",
            "--audio-format",
            "wav",
            "-o",
            str(audio_path),
            "--",  # end of options: the URL can never be parsed as a flag
            url,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    transcript_path = source_dir / "transcript.txt"
    _transcribe_audio(audio_path, transcript_path)

    store.update_source_status(source["id"], status="ready", error_message=None)


def _extract_audio(media_path: Path, audio_path: Path) -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is not installed")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(media_path),
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(audio_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _transcribe_audio(audio_path: Path, transcript_path: Path) -> None:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is required for local transcription. "
            "Install with: pip install faster-whisper"
        ) from exc

    model = WhisperModel("base", device="cpu", compute_type="int8")
    segments, _info = model.transcribe(str(audio_path))
    lines = [segment.text.strip() for segment in segments if segment.text.strip()]
    transcript_path.write_text("\n".join(lines), encoding="utf-8")
