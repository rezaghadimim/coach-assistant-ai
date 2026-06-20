"""Tests for direct client lookup intent detection."""

import unittest

from app.api.chat import reset_runtime_state, store
from app.core.client_intents import (
    detect_client_lookup,
    detect_client_mention,
    detect_confirm,
    detect_create_client,
    detect_list_clients,
    detect_profile_update,
    is_coaching_advice_request,
    is_simple_greeting,
    looks_like_malformed_tool_call,
    parse_text_tool_call,
    profile_update_from_add_note,
    try_direct_client_action,
    try_direct_client_query,
)
from app.core.llm import _sanitize_assistant_reply, try_direct_reply
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

    def test_detect_mobile_field_lookup(self) -> None:
        # Regression: "mobile" must be recognised as a contact field so the query
        # routes to a profile lookup instead of deflecting to the LLM.
        self.assertEqual(detect_client_lookup("what is Ali's mobile"), "Ali")
        self.assertEqual(detect_client_lookup("what is Ali's mobile profile"), "Ali")
        self.assertEqual(detect_client_lookup("what is Sara's cell number"), "Sara")

    def test_mobile_query_is_data_request(self) -> None:
        # Regression: a "mobile"/contact lookup must count as a data request so
        # follow-up deflections are suppressed and the LLM-router fallback fires.
        from app.core.llm import _is_data_request

        self.assertTrue(_is_data_request("what is Ali's mobile"))
        self.assertTrue(_is_data_request("show me Sara's cell number"))

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

    def test_coaching_advice_request_detected(self) -> None:
        self.assertTrue(
            is_coaching_advice_request(
                "In general I want to know one way about make patient happier"
            )
        )
        self.assertTrue(is_coaching_advice_request("How can I support Ali emotionally?"))
        self.assertTrue(is_coaching_advice_request("What should I ask Ali in our next session?"))

    def test_explicit_note_save_is_not_coaching_advice(self) -> None:
        self.assertFalse(
            is_coaching_advice_request("Note that Ali decided to change careers.")
        )
        self.assertFalse(
            is_coaching_advice_request("Save a goal for Ali: run a half marathon.")
        )
        self.assertFalse(
            is_coaching_advice_request("Add note for Ali: she prefers morning sessions.")
        )

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

    def test_detect_profile_update_age(self) -> None:
        execute_tool(
            "create_client",
            {"client_id": "ali", "name": "Ali", "confirmed": True},
            store,
        )
        self.assertEqual(
            detect_profile_update("Ali is 23 years old", store),
            {"client_id": "ali", "name": "Ali", "age": 23},
        )

    def test_detect_profile_update_age_with_profile_suffix(self) -> None:
        execute_tool(
            "create_client",
            {"client_id": "ali", "name": "Ali", "confirmed": True},
            store,
        )
        self.assertEqual(
            detect_profile_update("Ali is 23 years old profile", store),
            {"client_id": "ali", "name": "Ali", "age": 23},
        )

    def test_detect_profile_update_add_age_for_client(self) -> None:
        execute_tool(
            "create_client",
            {"client_id": "ali", "name": "Ali", "confirmed": True},
            store,
        )
        self.assertEqual(
            detect_profile_update("Add age for ali 13", store),
            {"client_id": "ali", "name": "Ali", "age": 13},
        )

    def test_detect_profile_update_add_age_for_client_typo(self) -> None:
        execute_tool(
            "create_client",
            {"client_id": "ali", "name": "Ali", "confirmed": True},
            store,
        )
        self.assertEqual(
            detect_profile_update("Add age for all 13", store),
            {"client_id": "ali", "name": "Ali", "age": 13},
        )

    def test_detect_profile_update_add_age_reverse_order(self) -> None:
        execute_tool(
            "create_client",
            {"client_id": "ali", "name": "Ali", "confirmed": True},
            store,
        )
        self.assertEqual(
            detect_profile_update("Add age 13 for ali", store),
            {"client_id": "ali", "name": "Ali", "age": 13},
        )

    def test_detect_profile_update_set_age_for_client(self) -> None:
        execute_tool(
            "create_client",
            {"client_id": "ali", "name": "Ali", "confirmed": True},
            store,
        )
        self.assertEqual(
            detect_profile_update("Set age for ali to 13", store),
            {"client_id": "ali", "name": "Ali", "age": 13},
        )

    def test_direct_profile_update_returns_update_client_preview(self) -> None:
        execute_tool(
            "create_client",
            {"client_id": "ali", "name": "Ali", "confirmed": True},
            store,
        )
        result = try_direct_client_action("Ali is 23 years old", store)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("Update client", result)
        self.assertIn("Age: 23", result)
        self.assertNotIn("Add note", result)

    def test_profile_update_from_add_note_redirects_age(self) -> None:
        execute_tool(
            "create_client",
            {"client_id": "ali", "name": "Ali", "confirmed": True},
            store,
        )
        self.assertEqual(
            profile_update_from_add_note(
                {
                    "client_id": "ali",
                    "content": "Ali is 23 years old",
                    "note_type": "general",
                },
                store,
            ),
            {"client_id": "ali", "name": "Ali", "age": 23},
        )

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

    def test_parse_text_tool_call_python_false_confirmed(self) -> None:
        """llama3.1 emits ``False`` (Python bool) instead of JSON ``false``."""
        raw = (
            '{"name": "create_client", "parameters": {"client_id": "ali", '
            '"name": "Ali", "email": "ali123@gmail.comk", "confirmed": False}}'
        )
        parsed = parse_text_tool_call(raw)
        self.assertIsNotNone(parsed, "parse_text_tool_call must handle Python-style False")
        assert parsed is not None
        tool_name, params = parsed
        self.assertEqual(tool_name, "create_client")
        self.assertEqual(params["client_id"], "ali")
        self.assertIs(params["confirmed"], False)

    def test_parse_text_tool_call_python_true_confirmed(self) -> None:
        """Python-style ``True`` (confirm reply) must also be parsed correctly."""
        raw = (
            '{"name": "create_client", "parameters": {"client_id": "ali", '
            '"name": "Ali", "confirmed": True}}'
        )
        parsed = parse_text_tool_call(raw)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        tool_name, params = parsed
        self.assertEqual(tool_name, "create_client")
        self.assertIs(params["confirmed"], True)

    def test_parse_text_tool_call_python_none_field(self) -> None:
        """Python ``None`` in optional fields must be parsed as ``null``."""
        raw = (
            '{"name": "add_client_note", "parameters": {"client_id": "ali", '
            '"content": "Great session", "note_type": "general", "title": None}}'
        )
        parsed = parse_text_tool_call(raw)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        tool_name, params = parsed
        self.assertEqual(tool_name, "add_client_note")
        self.assertIsNone(params["title"])

    def test_python_false_confirmed_executes_preview_not_raw_json(self) -> None:
        """When the LLM emits ``confirmed: False`` (Python style), the tool is
        executed and a ⏳ preview is returned — NOT the raw JSON string."""
        from app.core.client_intents import parse_text_tool_call
        from app.core.tools import execute_tool, sanitize_write_confirmation

        raw = (
            '{"name": "create_client", "parameters": {"client_id": "ali", '
            '"name": "Ali", "email": "ali123@gmail.comk", "confirmed": False}}'
        )
        result = parse_text_tool_call(raw)
        self.assertIsNotNone(result, "Tool call with Python False must be parseable")
        assert result is not None
        tool_name, params = result
        params = sanitize_write_confirmation(tool_name, params, "update Ali's email")
        tool_result = execute_tool(tool_name, params, store)
        self.assertTrue(
            tool_result.startswith("⏳"),
            f"Expected ⏳ preview, got: {tool_result!r}",
        )

    def test_confirm_flow_after_python_false_preview(self) -> None:
        """Full confirm flow: Python-False tool call → ⏳ → 'yes' → ✅."""
        from app.core.client_intents import try_direct_client_action

        reset_runtime_state()
        store.upsert_user("ali", name="Ali", profile={"phone": "9892323442"}, is_coach=False)

        raw = (
            '{"name": "create_client", "parameters": {"client_id": "ali", '
            '"name": "Ali", "email": "ali123@gmail.comk", "phone": "9892323442", '
            '"confirmed": False}}'
        )
        result = parse_text_tool_call(raw)
        self.assertIsNotNone(result)
        assert result is not None
        tool_name, params = result
        from app.core.tools import sanitize_write_confirmation, execute_tool
        params = sanitize_write_confirmation(tool_name, params, "update Ali's email")
        preview = execute_tool(tool_name, params, store)
        self.assertTrue(preview.startswith("⏳"), f"Expected ⏳, got {preview!r}")

        history = [
            {"role": "user", "content": "update Ali's email to be ali123@gmail.comk"},
            {"role": "assistant", "content": preview},
            {"role": "user", "content": "yes"},
        ]
        confirmed = try_direct_client_action("yes", store, history)
        self.assertIsNotNone(confirmed)
        assert confirmed is not None
        self.assertTrue(
            confirmed.startswith("✅"),
            f"Expected ✅ after confirm, got: {confirmed!r}",
        )

    def test_is_simple_greeting(self) -> None:
        self.assertTrue(is_simple_greeting("Hi"))
        self.assertTrue(is_simple_greeting("Hello there!"))
        self.assertTrue(is_simple_greeting("Good morning coach"))
        self.assertFalse(is_simple_greeting("Hi Ali, add a note"))

    def test_try_direct_reply_handles_greeting(self) -> None:
        reply = try_direct_reply("Hi", store)
        self.assertIsNotNone(reply)
        assert reply is not None
        self.assertIn("Coach Assistant AI", reply)

    def test_looks_like_malformed_tool_call(self) -> None:
        raw = (
            "Since your prompt doesn't specify a particular function call, "
            'I\'ll provide an empty response in the required JSON format.\n'
            '{"name": null, "parameters": {}}'
        )
        self.assertTrue(looks_like_malformed_tool_call(raw))
        self.assertFalse(
            looks_like_malformed_tool_call(
                '{"tool": "list_clients", "parameters": {}}'
            )
        )


class ToolRouterWiringTests(unittest.TestCase):
    """End-to-end tests confirming the tool router is correctly wired
    into try_direct_client_action() for common misrouting scenarios."""

    def setUp(self) -> None:
        import os
        os.environ.setdefault("TOOL_ROUTER_BACKEND", "token")
        os.environ.setdefault("TOOL_ROUTER_THRESHOLD", "0.40")
        os.environ.setdefault("TOOL_ROUTER_MARGIN", "0.05")
        reset_runtime_state()
        from app.core.tool_router import build_index, reset_index
        reset_index()
        build_index()

    def tearDown(self) -> None:
        from app.core.tool_router import reset_index
        reset_index()

    def _register_ali(self) -> None:
        execute_tool(
            "create_client",
            {"client_id": "ali", "name": "Ali", "confirmed": True},
            store,
        )

    # ------------------------------------------------------------------
    # The main bug fix: age updates must NOT create add_client_note rows
    # ------------------------------------------------------------------

    def test_age_is_routes_to_create_client_preview(self) -> None:
        self._register_ali()
        result = try_direct_client_action("Ali is 23 years old", store)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("Update client", result)
        self.assertIn("Age: 23", result)
        self.assertNotIn("Add note", result)

    def test_age_possessive_routes_to_create_client_preview(self) -> None:
        self._register_ali()
        result = try_direct_client_action("Ali's age is 23", store)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("Update client", result)
        self.assertIn("Age: 23", result)

    def test_age_set_routes_to_create_client_preview(self) -> None:
        self._register_ali()
        result = try_direct_client_action("Set Ali's age to 30", store)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("30", result)

    def test_email_set_routes_to_create_client_preview(self) -> None:
        self._register_ali()
        result = try_direct_client_action(
            "Update Ali's email to be ali123@gmail.co", store
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("Update client", result)
        self.assertIn("ali123@gmail.co", result)
        self.assertIn("pending confirmation", result)
        user = store.get_user("ali")
        self.assertIsNone(user["profile"].get("email"))

    def test_email_set_change_form(self) -> None:
        self._register_ali()
        result = try_direct_client_action(
            "Change Ali's email to ali2@example.com", store
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("ali2@example.com", result)

    def test_email_set_address_variant(self) -> None:
        self._register_ali()
        result = try_direct_client_action(
            "Set Ali's email address to ali@company.io", store
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("ali@company.io", result)

    def test_email_for_client(self) -> None:
        self._register_ali()
        result = try_direct_client_action(
            "Set email for Ali to ali@work.com", store
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("ali@work.com", result)

    def test_email_set_does_not_return_profile_lookup(self) -> None:
        """Regression: 'update email to be' must not fall through to get_client."""
        self._register_ali()
        result = try_direct_client_action(
            "Update Ali's email to be ali123@gmail.co", store
        )
        self.assertIsNotNone(result)
        assert result is not None
        # Must be a write preview, NOT a read-only profile card
        self.assertNotIn("Here are the details on file", result)
        self.assertNotIn("Profile\nClient ID", result)

    def test_unhandled_profile_write_defers_to_llm(self) -> None:
        """A profile-edit phrasing no extractor parses must defer to the LLM.

        It must NOT leak into the read-only path and return a profile card.
        """
        self._register_ali()
        # "make ... email ..." is not covered by any extractor regex.
        result = try_direct_client_action(
            "Make Ali's email ali@x.com", store
        )
        self.assertIsNone(result)

    def test_profile_read_still_works_after_write_guard(self) -> None:
        """The write guard must not block legitimate read lookups."""
        self._register_ali()
        result = try_direct_client_action("Show me Ali's details", store)
        self.assertIsNotNone(result)

    def test_phone_set_routes_to_create_client_preview(self) -> None:
        self._register_ali()
        result = try_direct_client_action(
            "Set Ali's phone to 9892323442", store
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("Update client", result)
        self.assertIn("Phone: 9892323442", result)
        self.assertIn("pending confirmation", result)
        user = store.get_user("ali")
        self.assertIsNone(user["profile"].get("phone"))

    def test_phone_set_to_be_form(self) -> None:
        self._register_ali()
        result = try_direct_client_action(
            "Update Ali's phone to be 09123456789", store
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("09123456789", result)

    def test_add_phone_for_client_routes_to_create_client_preview(self) -> None:
        self._register_ali()
        result = try_direct_client_action(
            "Set phone for ali 9892323442", store
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("Update client", result)
        self.assertIn("Phone: 9892323442", result)

    def test_add_age_for_client_routes_to_create_client_preview(self) -> None:
        self._register_ali()
        result = try_direct_client_action("Add age for ali 13", store)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("Update client", result)
        self.assertIn("Age: 13", result)
        self.assertNotIn("Age: 23", result)

    def test_age_update_does_not_create_note(self) -> None:
        self._register_ali()
        # Simulate a confirmation flow so the profile is actually saved.
        preview = try_direct_client_action("Ali is 23 years old", store)
        assert preview is not None
        history = [
            {"role": "user", "content": "Ali is 23 years old"},
            {"role": "assistant", "content": preview},
            {"role": "user", "content": "yes"},
        ]
        result = try_direct_client_action("yes", store, history)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("saved successfully", result)
        # Confirm no stray note was written
        notes = store.get_client_notes("ali")
        age_notes = [n for n in notes if "23" in (n.get("content") or "")]
        self.assertEqual(len(age_notes), 0, "Age update should not create a note")

    # ------------------------------------------------------------------
    # Tool router wiring for read tools
    # ------------------------------------------------------------------

    def test_router_list_clients_via_try_direct(self) -> None:
        self._register_ali()
        result = try_direct_client_action("Who are my clients?", store)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("Ali", result)

    def test_router_get_client_full_via_try_direct(self) -> None:
        self._register_ali()
        result = try_direct_client_action("Show me everything about Ali", store)
        self.assertIsNotNone(result)

    def test_router_list_notes_goals(self) -> None:
        self._register_ali()
        execute_tool(
            "add_client_note",
            {
                "client_id": "ali",
                "content": "Run 3x per week",
                "note_type": "goal",
                "confirmed": True,
            },
            store,
        )
        result = try_direct_client_action("What are Ali's goals?", store)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("Run 3x per week", result)


if __name__ == "__main__":
    unittest.main()
