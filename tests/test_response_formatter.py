"""Tests for app/core/response_formatter.py."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.chat import reset_runtime_state, store


def _make_provider(content: str) -> MagicMock:
    """Return a mock LLMProvider whose complete() returns *content*."""
    result = MagicMock()
    result.content = content
    provider = MagicMock()
    provider.complete = AsyncMock(return_value=result)
    return provider


class IsFormattableTests(unittest.TestCase):
    """Unit tests for :func:`~app.core.response_formatter.is_formattable`."""

    def setUp(self) -> None:
        from app.core.response_formatter import is_formattable
        self.is_formattable = is_formattable

    def test_true_for_data_reply(self) -> None:
        self.assertTrue(
            self.is_formattable(
                "Here are the details on file:\n\nClient ID: ali\nName: Ali"
            )
        )

    def test_false_for_write_preview(self) -> None:
        self.assertFalse(
            self.is_formattable("⏳ Create client — pending confirmation (not saved yet).")
        )

    def test_false_for_success_outcome(self) -> None:
        self.assertFalse(self.is_formattable("✅ Client 'ali' created."))

    def test_false_for_error(self) -> None:
        self.assertFalse(self.is_formattable("❌ Client 'ali' not found."))

    def test_false_for_empty_string(self) -> None:
        self.assertFalse(self.is_formattable(""))

    def test_false_for_plain_text(self) -> None:
        self.assertFalse(self.is_formattable("Hello! How can I help you today?"))

    def test_false_for_scope_refusal(self) -> None:
        self.assertFalse(
            self.is_formattable(
                "This coaching assistant is focused on life-coaching topics only."
            )
        )


class FormatDataReplyTests(unittest.IsolatedAsyncioTestCase):
    """Unit tests for :func:`~app.core.response_formatter.format_data_reply`."""

    async def test_returns_friendly_text_when_pii_preserved(self) -> None:
        from app.core.response_formatter import format_data_reply

        provider = _make_provider("Ali's email address is ali@example.com.")
        raw = "Here are the details on file:\n\nClient ID: ali\nEmail: ali@example.com"
        result = await format_data_reply("what is ali's email", raw, provider)

        self.assertEqual(result, "Ali's email address is ali@example.com.")

    async def test_preserves_email_in_formatted_output(self) -> None:
        from app.core.response_formatter import format_data_reply

        provider = _make_provider("You can reach Ali at ali@example.com.")
        raw = "Here are the details on file:\n\nClient ID: ali\nEmail: ali@example.com"
        result = await format_data_reply("give me ali's email", raw, provider)

        self.assertIn("ali@example.com", result)

    async def test_focused_reply_allowed_without_all_source_pii(self) -> None:
        """LLM answers only the email question — phone not repeated — this is correct."""
        from app.core.response_formatter import format_data_reply

        # Source has both email and phone; focused reply only mentions email.
        provider = _make_provider("Ali's email is ali@example.com.")
        raw = (
            "Here are the details on file:\n\n"
            "Client ID: ali\nEmail: ali@example.com\nPhone: +1-555-0101"
        )
        result = await format_data_reply("what is ali's email", raw, provider)

        # Focused reply is accepted — phone not required in output.
        self.assertEqual(result, "Ali's email is ali@example.com.")
        self.assertIn("ali@example.com", result)

    async def test_falls_back_when_llm_hallucinates_email(self) -> None:
        """LLM invents an email not in source → PII validation fails → fallback."""
        from app.core.response_formatter import format_data_reply

        provider = _make_provider("Ali's email is fake@evil.com.")
        raw = "Here are the details on file:\n\nClient ID: ali\nEmail: ali@example.com"
        result = await format_data_reply("what is ali's email", raw, provider)

        self.assertEqual(result, raw)
        self.assertNotIn("fake@evil.com", result)

    async def test_falls_back_on_llm_error(self) -> None:
        """Provider raises an exception → deterministic fallback returned."""
        from app.core.response_formatter import format_data_reply

        provider = MagicMock()
        provider.complete = AsyncMock(side_effect=RuntimeError("Ollama unavailable"))
        raw = "Here are the details on file:\n\nClient ID: ali\nName: Ali\nAge: 30"
        result = await format_data_reply("show ali's profile", raw, provider)

        self.assertEqual(result, raw)

    async def test_falls_back_on_empty_llm_reply(self) -> None:
        """LLM returns empty string → deterministic fallback returned."""
        from app.core.response_formatter import format_data_reply

        provider = _make_provider("")
        raw = "Here are the details on file:\n\nClient ID: ali\nName: Ali"
        result = await format_data_reply("show ali", raw, provider)

        self.assertEqual(result, raw)

    async def test_passes_through_error_strings_unchanged(self) -> None:
        """❌ errors are returned immediately without calling the provider."""
        from app.core.response_formatter import format_data_reply

        provider = MagicMock()
        provider.complete = AsyncMock()
        result = await format_data_reply("show ali", "❌ Client 'ali' not found.", provider)

        self.assertEqual(result, "❌ Client 'ali' not found.")
        provider.complete.assert_not_called()

    async def test_passes_through_write_previews_unchanged(self) -> None:
        """⏳ previews are returned immediately without calling the provider."""
        from app.core.response_formatter import format_data_reply

        provider = MagicMock()
        provider.complete = AsyncMock()
        preview = "⏳ Create client — pending confirmation (not saved yet)."
        result = await format_data_reply("add ali as client", preview, provider)

        self.assertEqual(result, preview)
        provider.complete.assert_not_called()

    async def test_passes_through_empty_string_unchanged(self) -> None:
        from app.core.response_formatter import format_data_reply

        provider = MagicMock()
        provider.complete = AsyncMock()
        result = await format_data_reply("show ali", "", provider)

        self.assertEqual(result, "")
        provider.complete.assert_not_called()

    async def test_phone_number_from_source_accepted(self) -> None:
        """Phone number in formatted reply that matches source is accepted."""
        from app.core.response_formatter import format_data_reply

        formatted_text = "Ali's phone number is +1-555-0101."
        provider = _make_provider(formatted_text)
        raw = "Here are the details on file:\n\nClient ID: ali\nPhone: +1-555-0101"
        result = await format_data_reply("what is ali's phone", raw, provider)

        self.assertEqual(result, formatted_text)
        self.assertIn("+1-555-0101", result)

    async def test_falls_back_when_llm_hallucinates_phone(self) -> None:
        """LLM invents a phone not in source → PII validation fails → fallback."""
        from app.core.response_formatter import format_data_reply

        provider = _make_provider("Ali's phone is +1-999-9999.")
        raw = "Here are the details on file:\n\nClient ID: ali\nPhone: +1-555-0101"
        result = await format_data_reply("what is ali's phone", raw, provider)

        self.assertEqual(result, raw)
        self.assertNotIn("+1-999-9999", result)

    async def test_no_data_without_prefix_passes_through(self) -> None:
        """A reply without the data prefix is returned unchanged."""
        from app.core.response_formatter import format_data_reply

        provider = MagicMock()
        provider.complete = AsyncMock()
        greeting = "Hello! How can I help you with coaching today?"
        result = await format_data_reply("hello", greeting, provider)

        self.assertEqual(result, greeting)
        provider.complete.assert_not_called()


class ResponseFormatterIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """Verify the formatter flag is respected in _generate_with_tools."""

    async def test_formatter_called_when_flag_enabled(self) -> None:
        """With response_formatter_enabled=True (default), format_data_reply is invoked."""
        from unittest.mock import patch as _patch

        from app.core.response_formatter import _DATA_REPLY_PREFIX

        data_reply = f"{_DATA_REPLY_PREFIX}Client ID: ali\nName: Ali"

        with (
            _patch("app.core.config.settings.response_formatter_enabled", True),  # default
            _patch("app.core.llm.try_direct_reply", return_value=data_reply),
            _patch(
                "app.core.response_formatter.format_data_reply",
                new=AsyncMock(return_value="Ali's profile is on file."),
            ) as mock_fmt,
        ):
            from app.core.llm import _generate_with_tools
            from app.core.tools import TOOL_DEFINITIONS

            provider = _make_provider("")
            store = MagicMock()
            messages = [{"role": "user", "content": "show ali"}]

            result = await _generate_with_tools(
                messages,
                "System prompt",
                TOOL_DEFINITIONS,
                store,
                provider,
            )

        mock_fmt.assert_called_once()
        self.assertEqual(result, "Ali's profile is on file.")

    async def test_formatter_skipped_when_flag_disabled(self) -> None:
        """With response_formatter_enabled=False (default), format_data_reply is not called."""
        from unittest.mock import patch as _patch

        from app.core.response_formatter import _DATA_REPLY_PREFIX

        data_reply = f"{_DATA_REPLY_PREFIX}Client ID: ali\nName: Ali"

        with (
            _patch("app.core.config.settings.response_formatter_enabled", False),
            _patch("app.core.llm.try_direct_reply", return_value=data_reply),
            _patch(
                "app.core.response_formatter.format_data_reply",
                new=AsyncMock(return_value="Should not be called."),
            ) as mock_fmt,
        ):
            from app.core.llm import _generate_with_tools
            from app.core.tools import TOOL_DEFINITIONS

            provider = _make_provider("")
            store = MagicMock()
            messages = [{"role": "user", "content": "show ali"}]

            result = await _generate_with_tools(
                messages,
                "System prompt",
                TOOL_DEFINITIONS,
                store,
                provider,
            )

        mock_fmt.assert_not_called()
        self.assertEqual(result, data_reply)


class FormatterConfirmFlowTests(unittest.IsolatedAsyncioTestCase):
    """Verify that the formatter does NOT interfere with write-preview / confirm flow.

    Regression suite for: LLM emits ``"confirmed": False`` (Python-style bool)
    instead of JSON ``false``.  Before the fix, ``parse_text_tool_call`` failed
    to parse the JSON, the raw tool-call text was stored as the assistant reply,
    and the subsequent "yes" confirmation found no pending-write preview in
    history — silently breaking the confirm flow with no test failure.
    """

    async def test_write_preview_not_formatted_with_formatter_enabled(self) -> None:
        """⏳ write previews are returned unchanged even when the formatter is on."""
        from unittest.mock import patch as _patch

        preview = (
            "⏳ Update client — pending confirmation (not saved yet).\n\n"
            "Client ID: ali\nName: Ali\nEmail: ali123@gmail.comk\n\n"
            "Are you sure you want to save this client? Reply yes or confirm to save."
        )

        with (
            _patch("app.core.config.settings.response_formatter_enabled", True),
            _patch("app.core.llm.try_direct_reply", return_value=preview),
            _patch(
                "app.core.response_formatter.format_data_reply",
                new=AsyncMock(return_value="Should not be called."),
            ) as mock_fmt,
        ):
            from app.core.llm import _generate_with_tools
            from app.core.tools import TOOL_DEFINITIONS

            provider = _make_provider("")
            store = MagicMock()
            messages = [
                {"role": "user", "content": "update Ali's email to be ali123@gmail.comk"}
            ]

            result = await _generate_with_tools(
                messages, "System prompt", TOOL_DEFINITIONS, store, provider
            )

        mock_fmt.assert_not_called()
        self.assertEqual(result, preview)
        self.assertTrue(result.startswith("⏳"))

    async def test_python_false_tool_call_produces_preview_not_raw_json(self) -> None:
        """LLM text reply with ``confirmed: False`` (Python) must yield ⏳, not raw JSON.

        This is the exact failure the bug report describes: llama3.1:8b returns a
        text tool call with Python-style ``False``.  The tool must be parsed,
        executed (confirmed=False → preview), and the ⏳ string returned.
        """
        from unittest.mock import patch as _patch

        reset_runtime_state()
        store.upsert_user("ali", name="Ali", profile={"phone": "9892323442"}, is_coach=False)

        llm_raw_json = (
            '{"name": "create_client", "parameters": {"client_id": "ali", '
            '"name": "Ali", "email": "ali123@gmail.comk", "phone": "9892323442", '
            '"age": 0, "background": "", "confirmed": False}}'
        )

        from app.core.llm_providers.types import CompletionResult

        llm_result = CompletionResult(
            content=llm_raw_json,
            tool_calls=[],
            assistant_message={"role": "assistant", "content": llm_raw_json},
        )
        provider = MagicMock()
        provider.complete = AsyncMock(return_value=llm_result)

        with _patch("app.core.config.settings.response_formatter_enabled", True):
            from app.core.llm import _generate_with_tools
            from app.core.tools import TOOL_DEFINITIONS

            messages = [
                {
                    "role": "user",
                    "content": "update Ali's email to be ali123@gmail.comk",
                }
            ]
            result = await _generate_with_tools(
                messages, "System prompt", TOOL_DEFINITIONS, store, provider
            )

        self.assertTrue(
            result.startswith("⏳"),
            f"Expected ⏳ preview, got: {result!r}",
        )
        self.assertNotIn('"confirmed": False', result)
        self.assertIn("ali123@gmail.comk", result)

    async def test_confirm_after_python_false_preview_saves_client(self) -> None:
        """After a ⏳ preview (from a Python-False tool call) the user says 'yes'
        and the client is actually saved (✅)."""
        from unittest.mock import patch as _patch

        from app.core.client_intents import parse_text_tool_call
        from app.core.tools import execute_tool, sanitize_write_confirmation

        reset_runtime_state()
        store.upsert_user("ali", name="Ali", profile={"phone": "9892323442"}, is_coach=False)

        llm_raw_json = (
            '{"name": "create_client", "parameters": {"client_id": "ali", '
            '"name": "Ali", "email": "ali123@gmail.comk", "confirmed": False}}'
        )

        parsed = parse_text_tool_call(llm_raw_json)
        self.assertIsNotNone(parsed, "parse_text_tool_call must handle Python False")
        assert parsed is not None
        tool_name, params = parsed
        params = sanitize_write_confirmation(
            tool_name, params, "update Ali's email to be ali123@gmail.comk"
        )
        preview = execute_tool(tool_name, params, store)
        self.assertTrue(preview.startswith("⏳"), f"Expected ⏳, got: {preview!r}")

        with _patch("app.core.config.settings.response_formatter_enabled", True):
            from app.core.llm import _generate_with_tools
            from app.core.tools import TOOL_DEFINITIONS
            from app.core.llm_providers.types import CompletionResult

            confirm_result = CompletionResult(
                content="", tool_calls=[],
                assistant_message={"role": "assistant", "content": ""},
            )
            provider = MagicMock()
            provider.complete = AsyncMock(return_value=confirm_result)

            history = [
                {
                    "role": "user",
                    "content": "update Ali's email to be ali123@gmail.comk",
                },
                {"role": "assistant", "content": preview},
            ]
            result = await _generate_with_tools(
                [*history, {"role": "user", "content": "yes"}],
                "System prompt",
                TOOL_DEFINITIONS,
                store,
                provider,
            )

        self.assertTrue(
            result.startswith("✅"),
            f"Expected ✅ success after confirm, got: {result!r}",
        )
        saved = store.get_user("ali")
        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertEqual(saved.get("profile", {}).get("email"), "ali123@gmail.comk")


if __name__ == "__main__":
    unittest.main()
