"""Tests for direct client lookup intent detection."""

import unittest

from app.api.chat import reset_runtime_state, store
from app.core.client_intents import (
    detect_client_lookup,
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

    def test_sanitize_strips_follow_up_json(self) -> None:
        raw = (
            '{"follow_ups": ["What are the next steps?", '
            '"How can I help Ali overcome his emotional thinking?"]}'
        )
        self.assertEqual(_sanitize_assistant_reply(raw), "")

    def test_sanitize_extracts_response_field(self) -> None:
        raw = '{"response": "Ali email is ali@example.com"}'
        self.assertEqual(
            _sanitize_assistant_reply(raw),
            "Ali email is ali@example.com",
        )


if __name__ == "__main__":
    unittest.main()
