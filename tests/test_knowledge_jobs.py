"""Tests for knowledge jobs (offline-safe)."""

from unittest.mock import patch

import pytest

from app.knowledge.jobs import (
    _process_youtube_source,
    _validate_local_media_path,
    _validate_video_url,
    process_pending_sources,
)
from app.knowledge.store import KnowledgeStore


def test_process_pending_marks_unsupported_source_failed(tmp_path) -> None:
    store = KnowledgeStore(str(tmp_path / "db.sqlite"))
    collection = store.create_collection(
        slug="demo",
        person_name="Demo",
        title="Demo",
    )
    source = store.create_source(
        collection["id"],
        title="Unknown",
        source_type="unsupported",
        uri="",
        status="pending",
    )
    process_pending_sources(knowledge_store=store, collections_dir=str(tmp_path))
    updated = store.get_source(source["id"])
    assert updated is not None
    assert updated["status"] == "failed"


def test_youtube_job_requires_yt_dlp(tmp_path) -> None:
    store = KnowledgeStore(str(tmp_path / "db.sqlite"))
    collection = store.create_collection(
        slug="yt",
        person_name="YT",
        title="YT",
    )
    source = store.create_source(
        collection["id"],
        title="Video",
        source_type="youtube",
        uri="https://www.youtube.com/watch?v=abc",
        status="pending",
    )
    with patch("app.knowledge.jobs.shutil.which", return_value=None):
        try:
            _process_youtube_source(store, collection, source, tmp_path)
        except RuntimeError as exc:
            assert "yt-dlp" in str(exc)
        else:
            raise AssertionError("expected RuntimeError")


# ------------------------------------------------------------------
# SEC-05 — ingest URI validation (SSRF / arg injection / local read)
# ------------------------------------------------------------------


def test_video_url_rejects_metadata_service() -> None:
    with pytest.raises(ValueError):
        _validate_video_url("http://169.254.169.254/latest/meta-data/")


def test_video_url_rejects_non_https_and_unknown_hosts() -> None:
    for uri in (
        "http://www.youtube.com/watch?v=abc",  # https required
        "https://evil.example.com/watch?v=abc",
        "https://youtube.com.evil.example/watch?v=abc",
        "file:///etc/passwd",
    ):
        with pytest.raises(ValueError):
            _validate_video_url(uri)


def test_video_url_accepts_allowed_hosts() -> None:
    assert _validate_video_url("https://www.youtube.com/watch?v=abc")
    assert _validate_video_url("https://youtu.be/abc")


def test_option_like_uri_rejected_before_yt_dlp(tmp_path) -> None:
    """A `--exec=...` URI must never reach the yt-dlp argv as a flag."""
    store = KnowledgeStore(str(tmp_path / "db.sqlite"))
    collection = store.create_collection(slug="yt2", person_name="YT", title="YT")
    source = store.create_source(
        collection["id"],
        title="Video",
        source_type="youtube",
        uri="--exec=touch /tmp/pwned",
        status="pending",
    )
    with pytest.raises(ValueError):
        _process_youtube_source(store, collection, source, tmp_path)


def test_yt_dlp_argv_uses_end_of_options_separator(tmp_path) -> None:
    """Even a valid URL is placed after `--` so it cannot be parsed as an option."""
    store = KnowledgeStore(str(tmp_path / "db.sqlite"))
    collection = store.create_collection(slug="yt3", person_name="YT", title="YT")
    source = store.create_source(
        collection["id"],
        title="Video",
        source_type="youtube",
        uri="https://www.youtube.com/watch?v=abc",
        status="pending",
    )
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)

        class Result:
            returncode = 0
            stderr = ""

        # Fake a produced subtitle so the audio-download branch is skipped.
        (tmp_path / "yt3" / "sources" / source["id"] / "transcript.vtt").write_text(
            "WEBVTT", encoding="utf-8"
        )
        return Result()

    with (
        patch("app.knowledge.jobs.shutil.which", return_value="/usr/bin/yt-dlp"),
        patch("app.knowledge.jobs.subprocess.run", side_effect=fake_run),
    ):
        _process_youtube_source(store, collection, source, tmp_path)

    assert calls, "yt-dlp was not invoked"
    argv = calls[0]
    assert argv[-1] == "https://www.youtube.com/watch?v=abc"
    assert argv[-2] == "--"


def test_local_media_outside_media_root_rejected(tmp_path) -> None:
    with pytest.raises(ValueError):
        _validate_local_media_path("/etc/passwd")


def test_local_media_inside_media_root_accepted(tmp_path) -> None:
    media_file = tmp_path / "clip.mp4"
    media_file.write_bytes(b"")
    with patch("app.knowledge.jobs.settings.media_root", str(tmp_path)):
        assert _validate_local_media_path(str(media_file)) == media_file.resolve()


def test_local_media_traversal_into_media_root_parent_rejected(tmp_path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("x", encoding="utf-8")
    with patch("app.knowledge.jobs.settings.media_root", str(root)):
        with pytest.raises(ValueError):
            _validate_local_media_path(str(root / ".." / "secret.txt"))


def test_local_media_source_fails_closed(tmp_path) -> None:
    """End-to-end: a pending local_media source outside media_root is marked failed."""
    store = KnowledgeStore(str(tmp_path / "db.sqlite"))
    collection = store.create_collection(slug="lm", person_name="LM", title="LM")
    store.create_source(
        collection["id"],
        title="Passwd",
        source_type="local_media",
        uri="/etc/passwd",
        status="pending",
    )
    processed = process_pending_sources(
        knowledge_store=store, collections_dir=str(tmp_path)
    )
    assert processed == []
    sources = store.list_sources(collection["id"])
    assert sources[0]["status"] == "failed"
    assert "media_root" in (sources[0]["error_message"] or "")
