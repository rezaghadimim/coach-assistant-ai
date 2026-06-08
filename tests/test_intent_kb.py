"""Tests for the offline intent knowledge-base classifier."""

import tempfile
import unittest
from pathlib import Path

from app.api.chat import store
from app.core.client_intents import try_direct_client_query
from app.core.intent_kb import classify
from app.core.tools import execute_tool


class IntentClassifyTests(unittest.TestCase):
    def test_goal_phrasings(self) -> None:
        cases = [
            "What are Ali's current goals and objectives?",
            "Show me Ali's goals",
            "What is Sara working toward?",
            "List Mohammad's objectives",
            "What goals does Ali have?",
            "What are the patient's objectives?",
        ]
        for message in cases:
            with self.subTest(message=message):
                match = classify(message)
                self.assertIsNotNone(match)
                assert match is not None
                self.assertEqual(match.tool, "list_client_notes")
                self.assertEqual(match.note_type, "goal")

    def test_decision_phrasings(self) -> None:
        match = classify("What decisions has Ali made?")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.note_type, "decision")

    def test_progress_phrasings(self) -> None:
        match = classify("What progress has Sara made?")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.note_type, "progress")

    def test_story_phrasings(self) -> None:
        match = classify("Tell me Ali's background story")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.note_type, "story")

    def test_list_clients(self) -> None:
        match = classify("Who are my clients?")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.tool, "list_clients")
        self.assertFalse(match.requires_client)

    def test_get_client_full(self) -> None:
        match = classify("Show me everything about Ali")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.tool, "get_client_full")

    def test_get_client_contact(self) -> None:
        match = classify("What is Ali's email?")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.tool, "get_client")

    def test_coaching_talk_does_not_classify(self) -> None:
        non_lookups = [
            "How can I support Ali emotionally?",
            "I feel stuck and unmotivated lately.",
            "Help me hold my client accountable this week.",
            "What questions should I ask Ali in our next session?",
        ]
        for message in non_lookups:
            with self.subTest(message=message):
                self.assertIsNone(classify(message))

    def test_empty_message(self) -> None:
        self.assertIsNone(classify("   "))


class KbDirectQueryTests(unittest.TestCase):
    """End-to-end KB fallback through try_direct_client_query."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = type(store)(str(Path(self._tmp.name) / "test.db"))
        execute_tool(
            "create_client",
            {"client_id": "ali", "name": "Ali", "confirmed": True},
            self.store,
        )
        execute_tool(
            "add_client_note",
            {
                "client_id": "ali",
                "content": "Run a half marathon by spring.",
                "note_type": "goal",
                "confirmed": True,
            },
            self.store,
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_kb_routes_goal_lookup_with_note_type(self) -> None:
        result = try_direct_client_query("What are Ali's goals?", self.store)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("Run a half marathon", result)

    def test_kb_routes_list_clients(self) -> None:
        result = try_direct_client_query("Who are my patients?", self.store)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("Ali", result)

    def test_kb_defers_for_unknown_client(self) -> None:
        self.assertIsNone(try_direct_client_query("What are Jordan's goals?", self.store))

    def test_kb_defers_for_coaching_talk(self) -> None:
        self.assertIsNone(
            try_direct_client_query("How can I support Ali emotionally?", self.store)
        )

    def test_kb_decision_lookup_empty(self) -> None:
        result = try_direct_client_query("What decisions has Ali made?", self.store)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("No notes of type 'decision'", result)


if __name__ == "__main__":
    unittest.main()
