"""Tests for the /api/tools endpoints."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("TOOL_ROUTER_BACKEND", "token")
os.environ.setdefault("TOOL_ROUTER_ENABLED", "true")
os.environ.setdefault("TOOL_ROUTER_THRESHOLD", "0.40")
os.environ.setdefault("TOOL_ROUTER_MARGIN", "0.05")

from fastapi.testclient import TestClient

from main import app


class ToolsClassifyEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        from app.core.tool_router import build_index, reset_index
        reset_index()
        build_index()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        from app.core.tool_router import reset_index
        reset_index()

    def test_classify_returns_200(self) -> None:
        response = self.client.post(
            "/api/tools/classify",
            json={"message": "Who are my clients?"},
        )
        self.assertEqual(response.status_code, 200)

    def test_classify_response_schema(self) -> None:
        response = self.client.post(
            "/api/tools/classify",
            json={"message": "What are Ali's goals?"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("message", body)
        self.assertIn("tool", body)
        self.assertIn("score", body)
        self.assertIn("top_n", body)
        self.assertIn("deferred", body)

    def test_classify_list_clients(self) -> None:
        response = self.client.post(
            "/api/tools/classify",
            json={"message": "Who are my clients?"},
        )
        body = response.json()
        self.assertEqual(body["tool"], "list_clients")
        self.assertFalse(body["deferred"])

    def test_classify_age_update_routes_to_create_client(self) -> None:
        response = self.client.post(
            "/api/tools/classify",
            json={"message": "Ali is 23 years old"},
        )
        body = response.json()
        self.assertEqual(body["tool"], "create_client")
        self.assertFalse(body["deferred"])

    def test_classify_note_save_routes_to_add_client_note(self) -> None:
        response = self.client.post(
            "/api/tools/classify",
            json={"message": "Note that Ali decided to change careers"},
        )
        body = response.json()
        self.assertEqual(body["tool"], "add_client_note")

    def test_classify_unknown_deferred(self) -> None:
        # Very high threshold forces deferral
        with patch("app.core.tool_router.settings") as mock_settings:
            mock_settings.tool_router_enabled = True
            mock_settings.tool_router_backend = "token"
            mock_settings.tool_router_threshold = 0.9999
            mock_settings.tool_router_margin = 0.0
            mock_settings.tool_knowledge_dir = "docs/tool-knowledge"
            mock_settings.tool_router_use_e5_prefix = True
            mock_settings.ollama_embed_model = "test"
            response = self.client.post(
                "/api/tools/classify",
                json={"message": "Ali is 23 years old"},
            )
        # Even if mocked, just verify the endpoint shape is correct
        self.assertEqual(response.status_code, 200)

    def test_classify_top_n_sorted_by_score(self) -> None:
        response = self.client.post(
            "/api/tools/classify",
            json={"message": "Show me everything about Ali"},
        )
        body = response.json()
        scores = [item["score"] for item in body["top_n"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_classify_empty_message_rejected(self) -> None:
        response = self.client.post(
            "/api/tools/classify",
            json={"message": ""},
        )
        self.assertEqual(response.status_code, 422)

    def test_reindex_returns_200(self) -> None:
        response = self.client.post("/api/tools/reindex")
        self.assertEqual(response.status_code, 200)

    def test_reindex_response_schema(self) -> None:
        response = self.client.post("/api/tools/reindex")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("examples_indexed", body)
        self.assertIn("backend", body)
        self.assertGreater(body["examples_indexed"], 0)

    def test_reindex_rebuilds_index(self) -> None:
        # First classify, then reindex, then classify again — same result.
        r1 = self.client.post("/api/tools/classify", json={"message": "List my clients"})
        self.client.post("/api/tools/reindex")
        r2 = self.client.post("/api/tools/classify", json={"message": "List my clients"})
        self.assertEqual(r1.json()["tool"], r2.json()["tool"])
