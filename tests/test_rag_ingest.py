"""Tests for core RAG ingestion chunking logic."""

import tempfile
import unittest
from pathlib import Path

from app.core.embed_providers import embed_profile_for_corpus
from app.rag.embed_cache import load_cache, save_cache
from app.rag.ingest import (
    build_document_chunks,
    chunk_text,
    discover_documents,
    discover_knowledge_documents,
    ingest_documents_from_dir,
    ingest_documents_from_dirs,
    read_document,
)


class RagIngestTests(unittest.TestCase):
    def test_chunk_text_uses_overlap(self) -> None:
        text = " ".join(f"t{i}" for i in range(20))
        chunks = chunk_text(text, chunk_size=8, chunk_overlap=2)

        self.assertEqual(len(chunks), 3)
        first_tokens = chunks[0].split()
        second_tokens = chunks[1].split()
        self.assertEqual(first_tokens[-2:], second_tokens[:2])

    def test_chunk_text_validates_chunk_config(self) -> None:
        with self.assertRaises(ValueError):
            chunk_text("a b c", chunk_size=4, chunk_overlap=4)

    def test_build_document_chunks_splits_markdown_sections(self) -> None:
        text = (
            "# Title\n\n"
            "Intro paragraph with enough words to chunk.\n\n"
            "## Section One\n\n"
            "First section content about GROW goals.\n\n"
            "## Section Two\n\n"
            "Second section about accountability."
        )
        chunks = build_document_chunks(text, source_path="guide.md", chunk_size=20, chunk_overlap=2)

        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(any("Section One" in chunk.text for chunk in chunks))
        self.assertTrue(any("Section Two" in chunk.text for chunk in chunks))

    def test_build_document_chunks_has_metadata(self) -> None:
        text = " ".join(f"word{i}" for i in range(12))
        chunks = build_document_chunks(text, source_path="guide.md", chunk_size=5, chunk_overlap=1)

        self.assertEqual(chunks[0].chunk_id, "guide.md:0")
        self.assertEqual(chunks[0].start_token, 0)
        self.assertEqual(chunks[0].end_token, 5)
        self.assertEqual(chunks[1].start_token, 4)
        self.assertEqual(chunks[1].text.split()[0], "word4")

    def test_discover_documents_filters_supported_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "a.txt").write_text("txt", encoding="utf-8")
            (root / "b.md").write_text("md", encoding="utf-8")
            (root / "c.pdf").write_text("not-a-real-pdf", encoding="utf-8")
            (root / "ignore.png").write_text("img", encoding="utf-8")
            nested = root / "nested"
            nested.mkdir()
            (nested / "d.txt").write_text("nested", encoding="utf-8")

            found = discover_documents(temp_dir)
            found_names = [path.name for path in found]

            self.assertEqual(found_names, ["a.txt", "b.md", "c.pdf", "d.txt"])

    def test_ingest_documents_from_dir_loads_txt_and_md(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "coaching.txt").write_text("goal reality options will", encoding="utf-8")
            (root / "notes.md").write_text("action accountability reflection", encoding="utf-8")

            chunks = ingest_documents_from_dir(temp_dir, chunk_size=3, chunk_overlap=1)

            self.assertGreaterEqual(len(chunks), 3)
            self.assertTrue(all(chunk.source_path.endswith((".txt", ".md")) for chunk in chunks))

    def test_read_document_reads_plain_text_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "doc.txt"
            path.write_text("line one\nline two", encoding="utf-8")

            content = read_document(str(path))
            self.assertEqual(content, "line one\nline two")

    def test_discover_knowledge_documents_private_overrides_starter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            starter = root / "starter"
            private = root / "private"
            starter.mkdir()
            private.mkdir()
            (starter / "grow.md").write_text("starter GROW content", encoding="utf-8")
            (private / "grow.md").write_text("private GROW override", encoding="utf-8")
            (private / "extra.md").write_text("private only doc", encoding="utf-8")

            found = discover_knowledge_documents(str(starter), str(private))
            found_names = sorted(path.name for path in found)

            self.assertEqual(found_names, ["extra.md", "grow.md"])
            grow_path = next(path for path in found if path.name == "grow.md")
            self.assertEqual(read_document(str(grow_path)), "private GROW override")

    def test_ingest_documents_from_dirs_merges_both_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            starter = root / "starter"
            private = root / "private"
            starter.mkdir()
            private.mkdir()
            (starter / "a.md").write_text("starter alpha beta", encoding="utf-8")
            (private / "b.md").write_text("private gamma delta", encoding="utf-8")

            chunks = ingest_documents_from_dirs(str(starter), str(private), chunk_size=5, chunk_overlap=1)
            sources = {Path(chunk.source_path).name for chunk in chunks}

            self.assertEqual(sources, {"a.md", "b.md"})

    def test_embed_cache_roundtrip(self) -> None:
        """save_cache → load_cache preserves vectors and identity header fields."""
        import json

        vectors = {"default::doc:0::abc123": [0.1, 0.2, 0.3]}
        profile = embed_profile_for_corpus("framework")
        with tempfile.TemporaryDirectory() as temp_dir:
            path = str(Path(temp_dir) / "cache.json")
            save_cache(path, vectors, profile)
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            self.assertEqual(raw["version"], 1)
            self.assertEqual(raw["model"], profile.model)
            self.assertEqual(raw["dim"], profile.dimensions)
            self.assertEqual(raw["chunks"], vectors)
            self.assertEqual(load_cache(path, profile), vectors)


if __name__ == "__main__":
    unittest.main()
