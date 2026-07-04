"""Background media processing for knowledge collections."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from app.core.config import settings
from app.knowledge.store import KnowledgeStore

logger = logging.getLogger(__name__)

_TRANSCRIPT_NAMES = ("transcript.txt", "transcript.vtt", "transcript.srt")

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


def process_pending_sources(
    *,
    knowledge_store: KnowledgeStore | None = None,
    collections_dir: str | None = None,
) -> list[str]:
    """Transcribe pending local media and fetch YouTube captions when possible."""
    store = knowledge_store or KnowledgeStore(settings.memory_db_path)
    root = Path(collections_dir or settings.rag_collections_dir)
    processed: list[str] = []

    for collection in store.list_collections():
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

    if shutil.which("yt-dlp") is None:
        raise RuntimeError("yt-dlp is not installed")

    subtitle_path = source_dir / "transcript.vtt"
    result = subprocess.run(
        [
            "yt-dlp",
            "--skip-download",
            "--write-auto-sub",
            "--write-sub",
            "--sub-format",
            "vtt",
            "--sub-lang",
            "en.*,en",
            "-o",
            str(source_dir / "video.%(ext)s"),
            "--",  # end of options: the URL can never be parsed as a flag
            url,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "yt-dlp failed")

    generated = list(source_dir.glob("*.vtt"))
    if not generated:
        audio_path = source_dir / "audio.wav"
        subprocess.run(
            [
                "yt-dlp",
                "-x",
                "--audio-format",
                "wav",
                "-o",
                str(audio_path),
                "--",
                url,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        transcript_path = source_dir / "transcript.txt"
        _transcribe_audio(audio_path, transcript_path)
    elif subtitle_path not in generated:
        generated[0].rename(subtitle_path)

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
