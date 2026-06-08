"""Tests for direct client lookup intent detection."""

import unittest

from app.api.chat import reset_runtime_state, store
from app.core.client_intents import (
    detect_client_lookup,
    detect_client_mention,
    detect_confirm,
    detect_create_client,
    detect_list_clients,
    parse_text_tool_call,
    try_direct_client_action,
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

    def test_detect_create_client_add_as_patient(self) -> None:
        self.assertEqual(
            detect_create_client("Add Hassan as another patient profile"),
            {"client_id": "hassan", "name": "Hassan"},
        )

    def test_detect_create_client_named_patient(self) -> None:
        self.assertEqual(
            detect_create_client("Register a new patient named Sara"),
            {"client_id": "sara", "name": "Sara"},
        )

    def test_detect_confirm(self) -> None:
        self.assertTrue(detect_confirm("yes"))
        self.assertTrue(detect_confirm("confirm"))
        self.assertFalse(detect_confirm("Add Hassan as a patient"))

    def test_direct_create_client_returns_preview(self) -> None:
        result = try_direct_client_action("Add Hassan as another patient", store)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("pending confirmation", result)
        self.assertIn("Client ID: hassan", result)

    def test_confirm_saves_pending_client(self) -> None:
        preview = try_direct_client_action("Add Hassan as another patient", store)
        assert preview is not None
        history = [
            {"role": "user", "content": "Add Hassan as another patient"},
            {"role": "assistant", "content": preview},
            {"role": "user", "content": "yes"},
        ]
        result = try_direct_client_action("yes", store, history)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("saved successfully", result)

    def test_parse_text_tool_call_from_error_wrapper(self) -> None:
        raw = (
            '{"error": "Invalid tool call. Please use the correct format: '
            '{"tool": "create_client", "parameters": {"client_id": "hassan", '
            '"name": "Hassan", "confirmed": "true"}}"}'
        )
        parsed = parse_text_tool_call(raw)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        tool_name, params = parsed
        self.assertEqual(tool_name, "create_client")
        self.assertEqual(params["client_id"], "hassan")


if __name__ == "__main__":
    unittest.main()
