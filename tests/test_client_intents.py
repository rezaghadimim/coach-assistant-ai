"""Tests for direct client lookup intent detection."""

import unittest

from app.api.chat import reset_runtime_state, store
from app.core.client_intents import (
    detect_client_lookup,
    detect_client_mention,
    detect_list_clients,
    try_direct_client_query,
)
from app.core.llm import _sanitize_assistant_reply
from app.core.tools import execute_tool


class ClientIntentTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime_state()

    def test_detect_possessive_detail_lookup(self) -> None:
        self.assertEqual(
            detect_client_lookup("Get me Ali's detail"),
            "Ali",
        )

    def test_detect_about_lookup(self) -> None:
        self.assertEqual(
            detect_client_lookup("Get all data about Ali patient"),
            "Ali",
        )

    def test_detect_everything_about_lookup(self) -> None:
        self.assertEqual(
            detect_client_lookup("Show me everything about Ali"),
            "Ali",
        )

    def test_detect_everything_about_lookup_returns_none_without_name(self) -> None:
        self.assertIsNone(detect_client_lookup("Show me everything about this patient"))

    def test_detect_list_clients(self) -> None:
        self.assertTrue(detect_list_clients("Who are my clients?"))

    def test_direct_query_returns_profile(self) -> None:
        execute_tool(
            "create_client",
            {
                "client_id": "ali",
                "name": "Ali",
                "email": "ali@example.com",
                "confirmed": True,
            },
            store,
        )
        result = try_direct_client_query("Get me Ali's detail", store)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("Email: ali@example.com", result)

    def test_sanitize_formats_follow_up_json_as_text(self) -> None:
        raw = (
            '{"follow_ups": ["What are the next steps?", '
            '"How can I help Ali overcome his emotional thinking?"]}'
        )
        result = _sanitize_assistant_reply(raw)
        self.assertIn("angles to explore", result)
        self.assertIn("What are the next steps?", result)

    def test_detect_client_mention_by_name(self) -> None:
        execute_tool(
            "create_client",
            {"client_id": "ali", "name": "Ali", "confirmed": True},
            store,
        )
        self.assertEqual(
            detect_client_mention("How can we best support Ali today?", store),
            "ali",
        )

    def test_detect_client_mention_ignores_unknown_names(self) -> None:
        self.assertIsNone(
            detect_client_mention("How can we best support Jordan today?", store)
        )

    def test_coaching_question_is_not_direct_lookup(self) -> None:
        execute_tool(
            "create_client",
            {"client_id": "ali", "name": "Ali", "confirmed": True},
            store,
        )
        self.assertIsNone(try_direct_client_query("How can we best support Ali today?", store))

    def test_sanitize_extracts_response_field(self) -> None:
        raw = '{"response": "Ali email is ali@example.com"}'
        self.assertEqual(
            _sanitize_assistant_reply(raw),
            "Ali email is ali@example.com",
        )


if __name__ == "__main__":
    unittest.main()
