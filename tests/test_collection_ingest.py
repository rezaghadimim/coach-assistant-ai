"""Tests for collection filesystem ingest."""

import json
from pathlib import Path

from app.knowledge.ingest import ingest_collection_chunks_from_disk
from app.knowledge.store import KnowledgeStore


def test_ingest_collection_from_disk(tmp_path) -> None:
    slug = "jane-doe"
    collection_dir = tmp_path / slug
    source_dir = collection_dir / "sources" / "grow-intro"
    source_dir.mkdir(parents=True)
    (collection_dir / "collection.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "person_name": "Jane Doe",
                "title": "Jane Doe",
            }
        ),
        encoding="utf-8",
    )
    (source_dir / "meta.json").write_text(
        json.dumps({"title": "GROW intro", "source_type": "transcript"}),
        encoding="utf-8",
    )
    (source_dir / "transcript.vtt").write_text(
        """WEBVTT

00:00:01.000 --> 00:00:04.000
Use the GROW model to structure the session.
""",
        encoding="utf-8",
    )

    db_path = tmp_path / "knowledge.db"
    store = KnowledgeStore(str(db_path))
    chunks = ingest_collection_chunks_from_disk(
        str(tmp_path),
        knowledge_store=store,
        chunk_size=50,
        chunk_overlap=10,
    )
    assert len(chunks) == 1
    assert chunks[0].person_name == "Jane Doe"
    assert chunks[0].source_title == "GROW intro"
    assert store.list_collections()[0]["source_count"] == 1
