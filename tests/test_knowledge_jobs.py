"""Tests for knowledge jobs (offline-safe)."""

from unittest.mock import patch

from app.knowledge.jobs import _process_youtube_source, process_pending_sources
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
        uri="https://example.com/watch?v=abc",
        status="pending",
    )
    with patch("app.knowledge.jobs.shutil.which", return_value=None):
        try:
            _process_youtube_source(store, collection, source, tmp_path)
        except RuntimeError as exc:
            assert "yt-dlp" in str(exc)
        else:
            raise AssertionError("expected RuntimeError")
