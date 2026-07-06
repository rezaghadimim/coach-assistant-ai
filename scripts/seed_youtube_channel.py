"""Seed a knowledge collection from a YouTube channel's captions.

Enumerates the most recent videos on a channel (via ``yt-dlp``) and fetches
English captions for each (via ``youtube-transcript-api``), writing them into
the on-disk collection format that ``scripts/seed_collections.py`` ingests:

    data/knowledge/collections/<slug>/
    ├── collection.json
    ├── SKIPPED.md                       # videos with no usable captions
    └── sources/<video_id>/
        ├── meta.json
        └── transcript.vtt

Why two tools: as of 2025 YouTube requires a PO token to download captions via
yt-dlp, but ``youtube-transcript-api`` uses a separate timedtext endpoint that
still works from a normal (residential) IP without auth. yt-dlp is used only to
list the channel's videos, which it does without issue.

Captions-only: no audio download, so ffmpeg/Whisper are NOT required here.
Videos with captions genuinely disabled are skipped and listed in SKIPPED.md as
a checklist for later Whisper processing (the app's pending-source job handles
that once ffmpeg + faster-whisper are installed).

Requires: ``yt-dlp`` and ``youtube-transcript-api`` (pip install both).

Examples:
    python3 scripts/seed_youtube_channel.py \
        --channel https://www.youtube.com/@TonyRobbinsLive \
        --slug tony-robbins --person-name "Tony Robbins" --limit 15

    # Then load into the RAG index (existing script, unchanged):
    python3 scripts/seed_collections.py --ingest
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

# English variants to accept, in preference order (manual before auto-generated
# is handled by the library's find_transcript ordering).
_LANGS = ["en", "en-US", "en-GB"]


class Blocked(Exception):
    """Raised when YouTube rate-limits / IP-blocks the request (transient)."""


def _fmt_ts(seconds: float) -> str:
    """Format seconds as a WebVTT timestamp: HH:MM:SS.mmm."""
    if seconds < 0:
        seconds = 0.0
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _snippets_to_vtt(snippets: list[dict]) -> str:
    """Render youtube-transcript-api snippets as a WebVTT document."""
    lines = ["WEBVTT", ""]
    for snip in snippets:
        start = float(snip["start"])
        end = start + float(snip.get("duration", 0.0))
        text = " ".join(snip["text"].split())  # collapse newlines/whitespace
        if not text:
            continue
        lines.append(f"{_fmt_ts(start)} --> {_fmt_ts(end)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def enumerate_videos(channel: str, limit: int) -> list[dict]:
    """Return [{id, title}, ...] for the ``limit`` most recent videos.

    Invoked as ``python -m yt_dlp`` so it works regardless of whether the
    yt-dlp console script is on PATH.
    """
    channel = channel.rstrip("/")
    if not channel.endswith(("/videos", "/streams", "/shorts")):
        channel += "/videos"
    argv = [sys.executable, "-m", "yt_dlp", "--flat-playlist", "--dump-json"]
    if limit > 0:  # limit <= 0 means "all videos"
        argv += ["--playlist-end", str(limit)]
    argv += ["--", channel]
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        sys.exit(f"Failed to list channel videos:\n{result.stderr.strip()}")

    videos: list[dict] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        entry = json.loads(line)
        vid = entry.get("id")
        if not vid:
            continue
        videos.append({"id": vid, "title": entry.get("title") or vid})
    return videos


def fetch_captions(api, video_id: str, source_dir: Path) -> str:
    """Fetch English captions and write transcript.vtt.

    Returns "" on success, or a short reason string for a PERMANENT skip
    (captions disabled / none / unavailable). Raises ``Blocked`` on a transient
    IP block / rate-limit so the caller can back off instead of mis-recording a
    good video as skipped.
    """
    from youtube_transcript_api import (
        NoTranscriptFound,
        TranscriptsDisabled,
        VideoUnavailable,
    )

    try:
        from youtube_transcript_api import IpBlocked, RequestBlocked
        block_errors: tuple = (IpBlocked, RequestBlocked)
    except ImportError:  # older lib: fall back to name-based detection below
        block_errors = ()

    try:
        fetched = api.fetch(video_id, languages=_LANGS)
    except TranscriptsDisabled:
        return "captions disabled"
    except NoTranscriptFound:
        return "no English transcript"
    except VideoUnavailable:
        return "video unavailable"
    except Exception as exc:
        if isinstance(exc, block_errors) or "block" in type(exc).__name__.lower():
            raise Blocked(str(exc)) from exc
        return f"error: {type(exc).__name__}"

    snippets = fetched.to_raw_data()
    if not snippets:
        return "empty transcript"

    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "transcript.vtt").write_text(
        _snippets_to_vtt(snippets), encoding="utf-8"
    )
    return ""


def write_meta(source_dir: Path, video_id: str, title: str) -> None:
    meta = {
        "title": title,
        "source_type": "youtube",
        "source_id": video_id,
        "uri": f"https://www.youtube.com/watch?v={video_id}",
    }
    (source_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def ensure_collection(coll_dir: Path, slug: str, person_name: str) -> None:
    coll_dir.mkdir(parents=True, exist_ok=True)
    coll_json = coll_dir / "collection.json"
    if coll_json.exists():
        return
    data = {
        "slug": slug,
        "person_name": person_name,
        "title": person_name,
        "description": f"YouTube coaching content from {person_name}",
    }
    coll_json.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_skipped(coll_dir: Path, skipped: list[dict]) -> None:
    """Write a checklist of captionless videos for later Whisper processing."""
    path = coll_dir / "SKIPPED.md"
    lines = [
        "# Skipped videos (no usable English captions)",
        "",
        "These videos had no fetchable English subtitles and were skipped by the",
        "caption seeder. To ingest one later, transcribe its audio with Whisper",
        "(the app's pending-source job handles this once ffmpeg + faster-whisper",
        "are installed).",
        "",
    ]
    if not skipped:
        lines.append("_None — every fetched video had captions._")
    else:
        for v in skipped:
            url = f"https://www.youtube.com/watch?v={v['id']}"
            lines.append(f"- [ ] {v['title']} — {url} _({v['reason']})_")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_proxy_config(args):
    """Build a youtube-transcript-api proxy config from CLI args, or None."""
    if args.webshare_user and args.webshare_pass:
        from youtube_transcript_api.proxies import WebshareProxyConfig

        return WebshareProxyConfig(
            proxy_username=args.webshare_user,
            proxy_password=args.webshare_pass,
        )
    if args.http_proxy or args.https_proxy:
        from youtube_transcript_api.proxies import GenericProxyConfig

        return GenericProxyConfig(
            http_url=args.http_proxy,
            https_url=args.https_proxy,
        )
    return None


def _fetch_with_backoff(api, video_id: str, source_dir: Path, retries: int = 3) -> str:
    """fetch_captions with exponential backoff on transient blocks."""
    delay = 30.0
    for attempt in range(1, retries + 1):
        try:
            return fetch_captions(api, video_id, source_dir)
        except Blocked:
            if attempt == retries:
                raise
            print(f"    ~ blocked, backing off {int(delay)}s (attempt {attempt}/{retries})")
            time.sleep(delay)
            delay *= 2
    return "error: unreachable"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed a collection from a YouTube channel's captions"
    )
    parser.add_argument(
        "--channel",
        default="https://www.youtube.com/@TonyRobbinsLive",
        help="Channel URL (the /videos tab is used automatically).",
    )
    parser.add_argument("--slug", default="tony-robbins", help="Collection slug.")
    parser.add_argument(
        "--person-name", default="Tony Robbins", help="Display name for the coach."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=15,
        help="Number of most-recent videos to fetch; 0 (or negative) means ALL.",
    )
    parser.add_argument(
        "--collections-dir",
        default="data/knowledge/private/collections",
        help="Root directory for on-disk collections. Defaults to the PRIVATE "
        "collections dir (scraped transcripts are real data, kept out of the "
        "public repo). Use data/knowledge/collections for public demo content.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=2.0,
        help="Seconds to pause between videos (raise this to avoid IP blocks).",
    )
    parser.add_argument(
        "--webshare-user",
        default=None,
        help="Webshare rotating-residential proxy username (recommended for bulk).",
    )
    parser.add_argument(
        "--webshare-pass",
        default=None,
        help="Webshare proxy password.",
    )
    parser.add_argument(
        "--http-proxy",
        default=None,
        help="Generic HTTP proxy URL (alternative to Webshare).",
    )
    parser.add_argument(
        "--https-proxy",
        default=None,
        help="Generic HTTPS proxy URL (alternative to Webshare).",
    )
    args = parser.parse_args()

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        sys.exit("youtube-transcript-api is not installed. Run: pip install youtube-transcript-api")

    api = YouTubeTranscriptApi(proxy_config=_build_proxy_config(args))
    coll_dir = Path(args.collections_dir) / args.slug
    ensure_collection(coll_dir, args.slug, args.person_name)

    print(f"Enumerating up to {args.limit or 'ALL'} recent videos from {args.channel} ...")
    videos = enumerate_videos(args.channel, args.limit)
    print(f"Found {len(videos)} video(s).")

    seeded, skipped = 0, []
    for i, v in enumerate(videos, 1):
        print(f"[{i}/{len(videos)}] {v['title']} ({v['id']})")
        source_dir = coll_dir / "sources" / v["id"]
        if (source_dir / "transcript.vtt").exists():
            print("    - already fetched, skipping")
            seeded += 1
            continue

        try:
            reason = _fetch_with_backoff(api, v["id"], source_dir)
        except Blocked as exc:
            # Persistent block: save progress and stop rather than condemning
            # every remaining good video to SKIPPED.md. Re-run to resume.
            if source_dir.exists() and not any(source_dir.iterdir()):
                source_dir.rmdir()
            write_skipped(coll_dir, skipped)
            print(f"\n! YouTube is blocking this IP ({exc}).")
            print(f"  Stopped at video {i}/{len(videos)}; {seeded} saved so far.")
            print("  Wait for the block to clear (or use --webshare-user/--webshare-pass")
            print("  or --http-proxy/--https-proxy), then re-run to resume where it left off.")
            sys.exit(2)

        if not reason:
            write_meta(source_dir, v["id"], v["title"])
            print("    + captions saved")
            seeded += 1
        else:
            if source_dir.exists() and not any(source_dir.iterdir()):
                source_dir.rmdir()
            skipped.append({**v, "reason": reason})
            print(f"    - skipped ({reason})")
        if args.sleep and i < len(videos):
            time.sleep(args.sleep)

    write_skipped(coll_dir, skipped)
    print(
        f"\nDone. Seeded {seeded} source(s), skipped {len(skipped)} "
        f"(see {coll_dir / 'SKIPPED.md'})."
    )
    print("Next: python3 scripts/seed_collections.py --ingest")


if __name__ == "__main__":
    main()
