"""Tests for core RAG ingestion chunking logic."""

import tempfile
import unittest
from pathlib import Path

from app.rag.ingest import (
    build_document_chunks,
    chunk_text,
    discover_documents,
    ingest_documents_from_dir,
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


if __name__ == "__main__":
    unittest.main()
