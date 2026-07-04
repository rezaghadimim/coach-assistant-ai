"""Tests for the tool router (token backend — no Ollama required)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Force token backend for all tests so they run offline.
os.environ.setdefault("TOOL_ROUTER_BACKEND", "token")
os.environ.setdefault("TOOL_ROUTER_ENABLED", "true")
os.environ.setdefault("TOOL_ROUTER_THRESHOLD", "0.50")
os.environ.setdefault("TOOL_ROUTER_MARGIN", "0.05")


class ToolRouterTokenBackendTests(unittest.TestCase):
    """Core token-backend classify() behaviour."""

    def setUp(self) -> None:
        from app.core.config import settings
        from app.core.tool_router import reset_index

        self._settings_patch = patch.multiple(
            settings,
            tool_router_backend="token",
            tool_router_rerank_enabled=False,
        )
        self._settings_patch.start()
        reset_index()

    def tearDown(self) -> None:
        from app.core.tool_router import reset_index

        reset_index()
        self._settings_patch.stop()

    # ------------------------------------------------------------------
    # index loading
    # ------------------------------------------------------------------

    def test_build_index_loads_routing_jsonl(self) -> None:
        from app.core.tool_router import build_index
        count = build_index()
        self.assertGreater(count, 0, "build_index should load examples from routing.jsonl")

    def test_token_backend_never_degraded(self) -> None:
        from app.core.tool_router import build_index, effective_backend, is_degraded
        build_index()
        self.assertEqual(effective_backend(), "token")
        self.assertFalse(is_degraded())


class ToolRouterDegradationTests(unittest.TestCase):
    """effective_backend()/is_degraded() reporting when auto falls back to token."""

    def tearDown(self) -> None:
        from app.core.tool_router import reset_index
        reset_index()

    def test_auto_reports_token_and_degraded_when_embed_unavailable(self) -> None:
        import app.core.tool_router as tr
        from app.core.config import settings
        with patch.multiple(settings, tool_router_backend="auto"):
            tr.reset_index()
            tr._embed_available = False  # simulate Ollama probe failure
            self.assertEqual(tr.effective_backend(), "token")
            self.assertTrue(tr.is_degraded())

    def test_explicit_embedding_backend_degraded_when_embed_unavailable(self) -> None:
        import app.core.tool_router as tr
        from app.core.config import settings
        with patch.multiple(settings, tool_router_backend="embedding"):
            tr.reset_index()
            tr._embed_available = False
            self.assertEqual(tr.effective_backend(), "token")
            self.assertTrue(tr.is_degraded())

    def test_build_index_idempotent(self) -> None:
        from app.core.tool_router import build_index
        count1 = build_index()
        count2 = build_index()
        self.assertEqual(count1, count2)

    def test_build_index_force_rebuilds(self) -> None:
        from app.core.tool_router import build_index
        count1 = build_index()
        count2 = build_index(force=True)
        self.assertEqual(count1, count2)

    def test_build_index_empty_dir_returns_zero(self) -> None:
        from app.core.tool_router import build_index, reset_index
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "examples").mkdir()
            with patch("app.core.tool_router.settings") as mock_settings:
                mock_settings.tool_router_enabled = True
                mock_settings.tool_router_backend = "token"
                mock_settings.tool_knowledge_dir = tmp
                mock_settings.tool_router_threshold = 0.5
                mock_settings.tool_router_margin = 0.05
                mock_settings.tool_router_use_e5_prefix = True
                mock_settings.ollama_embed_model = "test"
                reset_index()
                count = build_index()
        self.assertEqual(count, 0)

    def test_build_index_custom_jsonl(self) -> None:
        from app.core.tool_router import build_index, classify_tool, reset_index
        with tempfile.TemporaryDirectory() as tmp:
            ex_dir = Path(tmp) / "examples"
            ex_dir.mkdir()
            (ex_dir / "routing.jsonl").write_text(
                json.dumps({"utterance": "list all clients", "tool": "list_clients", "hint": "all"}) + "\n"
                + json.dumps({"utterance": "add Ali as a new client", "tool": "create_client", "hint": "new_client"}) + "\n",
                encoding="utf-8",
            )
            with patch("app.core.tool_router.settings") as mock_settings:
                mock_settings.tool_router_enabled = True
                mock_settings.tool_router_backend = "token"
                mock_settings.tool_knowledge_dir = tmp
                mock_settings.tool_router_threshold = 0.3
                mock_settings.tool_router_margin = 0.05
                mock_settings.tool_router_use_e5_prefix = True
                mock_settings.ollama_embed_model = "test"
                reset_index()
                count = build_index()
                match = classify_tool("list all clients", threshold=0.3, margin=0.05)
        self.assertEqual(count, 2)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.tool, "list_clients")

    # ------------------------------------------------------------------
    # create_client vs add_client_note (the main bug)
    # ------------------------------------------------------------------

    def test_age_update_routes_to_create_client(self) -> None:
        from app.core.tool_router import classify_tool
        build_router()
        match = classify_tool("Ali is 23 years old", threshold=0.4, margin=0.05)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.tool, "create_client")
        self.assertEqual(match.backend, "token")

    def test_age_possessive_routes_to_create_client(self) -> None:
        from app.core.tool_router import classify_tool
        build_router()
        match = classify_tool("Ali's age is 23", threshold=0.4, margin=0.05)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.tool, "create_client")

    def test_note_decision_routes_to_add_client_note(self) -> None:
        from app.core.tool_router import classify_tool
        build_router()
        match = classify_tool("Note that Ali decided to change careers", threshold=0.3, margin=0.05)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.tool, "add_client_note")

    def test_save_goal_routes_to_add_client_note(self) -> None:
        from app.core.tool_router import classify_tool
        build_router()
        match = classify_tool("Save a goal for Ali: run 3 times per week", threshold=0.3, margin=0.05)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.tool, "add_client_note")

    # ------------------------------------------------------------------
    # read tools
    # ------------------------------------------------------------------

    def test_list_clients(self) -> None:
        from app.core.tool_router import classify_tool
        build_router()
        match = classify_tool("Who are my clients?", threshold=0.3, margin=0.05)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.tool, "list_clients")

    def test_list_notes_goals(self) -> None:
        from app.core.tool_router import classify_tool
        build_router()
        match = classify_tool("What are Ali's goals?", threshold=0.3, margin=0.05)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.tool, "list_client_notes")

    def test_get_client_full(self) -> None:
        from app.core.tool_router import classify_tool
        build_router()
        match = classify_tool("Show me everything about Ali", threshold=0.3, margin=0.05)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.tool, "get_client_full")

    def test_get_client_email(self) -> None:
        from app.core.tool_router import classify_tool
        build_router()
        match = classify_tool("What is Ali's email?", threshold=0.3, margin=0.05)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.tool, "get_client")

    def test_update_client_note(self) -> None:
        from app.core.tool_router import classify_tool
        build_router()
        match = classify_tool("Update note 3 to: Ali now runs 5 times per week", threshold=0.3, margin=0.05)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.tool, "update_client_note")

    def test_delete_note(self) -> None:
        from app.core.tool_router import classify_tool
        build_router()
        match = classify_tool("Delete note 3", threshold=0.3, margin=0.05)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.tool, "delete_client_note")

    def test_delete_client(self) -> None:
        from app.core.tool_router import classify_tool
        build_router()
        match = classify_tool("Delete client Ali", threshold=0.3, margin=0.05)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.tool, "delete_client")

    # ------------------------------------------------------------------
    # threshold / margin / disabled
    # ------------------------------------------------------------------

    def test_below_threshold_returns_none(self) -> None:
        from app.core.tool_router import classify_tool
        build_router()
        # Cosine similarity is always <= 1.0; threshold > 1.0 forces no match.
        match = classify_tool("Ali is 23 years old", threshold=1.1)
        self.assertIsNone(match)

    def test_disabled_returns_none(self) -> None:
        from app.core.tool_router import classify_tool
        with patch("app.core.tool_router.settings") as mock_settings:
            mock_settings.tool_router_enabled = False
            result = classify_tool("Ali is 23 years old")
        self.assertIsNone(result)

    def test_top_n_returns_sorted_candidates(self) -> None:
        from app.core.tool_router import top_n_tools
        build_router()
        top = top_n_tools("What are Ali's goals?", n=3)
        self.assertGreater(len(top), 0)
        # Sorted by descending score
        scores = [m.score for m in top]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_match_includes_hint(self) -> None:
        from app.core.tool_router import classify_tool
        build_router()
        match = classify_tool("What are Ali's goals?", threshold=0.3, margin=0.05)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertIsNotNone(match.hint)


def build_router() -> None:
    """Ensure the token index is built."""
    from app.core.tool_router import _index_built, build_index
    if not _index_built:
        build_index()


class OutOfVocabWithLexiconTests(unittest.TestCase):
    """Token-backend tests for out-of-vocab phrasings helped by the lexicon."""

    def setUp(self) -> None:
        from app.core.config import settings
        from app.core.tool_router import reset_index

        self._settings_patch = patch.multiple(
            settings,
            tool_router_backend="token",
            tool_router_rerank_enabled=False,
        )
        self._settings_patch.start()
        reset_index()
        build_router()

    def tearDown(self) -> None:
        from app.core.tool_router import reset_index

        reset_index()
        self._settings_patch.stop()

    def test_visitors_in_table_routes_list_clients(self) -> None:
        from app.core.tool_router import classify_tool
        match = classify_tool("Give me all visitors in table", threshold=0.15, margin=0.05)
        self.assertIsNotNone(match, "Lexicon expansion should match list_clients")
        assert match is not None
        self.assertEqual(match.tool, "list_clients")

    def test_roster_routes_list_clients(self) -> None:
        from app.core.tool_router import classify_tool
        match = classify_tool("Dump the roster", threshold=0.15, margin=0.05)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.tool, "list_clients")

    def test_database_routes_list_clients(self) -> None:
        from app.core.tool_router import classify_tool
        match = classify_tool("Who is in the database?", threshold=0.15, margin=0.05)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.tool, "list_clients")

    def test_contacts_routes_list_clients(self) -> None:
        from app.core.tool_router import classify_tool
        match = classify_tool("Fetch all contacts", threshold=0.15, margin=0.05)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.tool, "list_clients")

    def test_aims_routes_list_client_notes(self) -> None:
        from app.core.tool_router import classify_tool
        match = classify_tool("What are Ali's aims?", threshold=0.15, margin=0.05)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.tool, "list_client_notes")

    def test_memos_routes_list_client_notes(self) -> None:
        from app.core.tool_router import classify_tool
        match = classify_tool("Pull up all memos for Ali", threshold=0.15, margin=0.05)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.tool, "list_client_notes")
