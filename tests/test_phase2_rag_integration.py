"""Phase 2 tests: ingestion + retrieval integration."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.api.chat import reset_runtime_state
from app.core.config import settings
from app.rag.retriever import clear_index, ingest_and_index_directory, retrieve
from main import app


class Phase2RagIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime_state()
        clear_index()
        self.client = TestClient(app)

    def test_ingest_and_retrieve_from_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "grow.txt").write_text(
                "Use the GROW model: goal reality options will.",
                encoding="utf-8",
            )
            (root / "questions.md").write_text(
                "Ask open ended coaching questions focused on reality.",
                encoding="utf-8",
            )

            docs_count, chunks_count = ingest_and_index_directory(
                temp_dir,
                chunk_size=30,
                chunk_overlap=5,
            )

            self.assertEqual(docs_count, 2)
            self.assertGreaterEqual(chunks_count, 2)

            results = retrieve("how to explore goal and reality", top_k=2, min_score=0.0)
            self.assertTrue(results)
            self.assertIn("grow", results[0].source_path)

    def test_ingest_endpoint_indexes_local_docs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "method.md").write_text("Values and accountability coaching", encoding="utf-8")

            original_docs_dir = settings.rag_docs_dir
            settings.rag_docs_dir = temp_dir
            try:
                response = self.client.post(
                    "/api/ingest",
                    json={"chunk_size": 20, "chunk_overlap": 2},
                )
            finally:
                settings.rag_docs_dir = original_docs_dir

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["documents_indexed"], 1)
        self.assertGreaterEqual(body["chunks_indexed"], 1)

    def test_chat_includes_rag_context_in_system_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "guide.txt").write_text(
                "Reality questions help clients examine current constraints.",
                encoding="utf-8",
            )
            ingest_and_index_directory(temp_dir, chunk_size=20, chunk_overlap=0)

            with patch(
                "app.api.chat.generate_response",
                new=AsyncMock(return_value="Let's explore your current reality."),
            ) as mocked_generate:
                response = self.client.post(
                    "/api/chat",
                    json={"user_id": "rag-user", "message": "How should I explore reality?"},
                )

        self.assertEqual(response.status_code, 200)
        system_prompt = mocked_generate.await_args.kwargs["system_prompt"]
        self.assertIn("Relevant Coaching Knowledge", system_prompt)
        self.assertIn("guide.txt", system_prompt)


if __name__ == "__main__":
    unittest.main()
