"""CQ-01/AI-01 — typed ToolOutcome and structured pending-write confirmation."""

import os
import tempfile
import unittest
from unittest.mock import patch

from app.core.client_intents import try_direct_client_action_with_meta
from app.core.confirmations import (
    clear_pending_writes,
    parse_pending_write,
    register_pending_write,
)
from app.core.tools import execute_tool, execute_tool_outcome
from app.memory.store import MemoryStore


class ToolOutcomeStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_pending_writes()
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.store = MemoryStore(self._tmp.name)
        self.store.upsert_user("ali", name="Ali", is_coach=False)

    def tearDown(self) -> None:
        clear_pending_writes()
        os.unlink(self._tmp.name)

    def test_read_returns_info(self) -> None:
        outcome = execute_tool_outcome("get_client", {"client_id": "ali"}, self.store)
        self.assertEqual(outcome.status, "info")
        self.assertFalse(outcome.is_terminal)
        self.assertIn("Ali", outcome.text)

    def test_unknown_client_returns_error(self) -> None:
        outcome = execute_tool_outcome("get_client", {"client_id": "nope"}, self.store)
        self.assertEqual(outcome.status, "error")
        self.assertTrue(outcome.is_terminal)

    def test_unconfirmed_write_returns_preview(self) -> None:
        outcome = execute_tool_outcome(
            "add_client_note",
            {"client_id": "ali", "content": "New goal", "note_type": "goal"},
            self.store,
        )
        self.assertEqual(outcome.status, "preview")
        self.assertTrue(outcome.is_terminal)
        self.assertEqual(self.store.get_client_notes("ali"), [])

    def test_confirmed_write_returns_ok(self) -> None:
        outcome = execute_tool_outcome(
            "add_client_note",
            {
                "client_id": "ali",
                "content": "New goal",
                "note_type": "goal",
                "confirmed": True,
            },
            self.store,
        )
        self.assertEqual(outcome.status, "ok")
        self.assertEqual(len(self.store.get_client_notes("ali")), 1)

    def test_unknown_tool_returns_error(self) -> None:
        outcome = execute_tool_outcome("nope_tool", {}, self.store)
        self.assertEqual(outcome.status, "error")

    def test_legacy_string_api_unchanged(self) -> None:
        text = execute_tool("get_client", {"client_id": "ali"}, self.store)
        self.assertIsInstance(text, str)
        self.assertIn("Ali", text)


class StructuredPendingWriteTests(unittest.TestCase):
    """Confirm-to-save replays the stored struct, not a re-parse of preview prose."""

    def setUp(self) -> None:
        clear_pending_writes()
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.store = MemoryStore(self._tmp.name)
        self.store.upsert_user("ali", name="Ali", is_coach=False)

    def tearDown(self) -> None:
        clear_pending_writes()
        os.unlink(self._tmp.name)

    def test_confirm_survives_reworded_preview_template(self) -> None:
        """The regression the old regex approach fails: new wording, no parse anchors."""
        reworded = "Ready when you are — nothing has been stored so far!"
        with patch(
            "app.core.tools._format_add_note_preview", return_value=reworded
        ):
            preview = execute_tool_outcome(
                "add_client_note",
                {"client_id": "ali", "content": "Ali committed to a design course",
                 "note_type": "decision", "title": "Course"},
                self.store,
            )
        self.assertEqual(preview.status, "preview")

        history = [
            {"role": "user", "content": "save a decision note for Ali"},
            {"role": "assistant", "content": preview.text},
        ]
        result = try_direct_client_action_with_meta("yes", self.store, history)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "ok")
        notes = self.store.get_client_notes("ali")
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["content"], "Ali committed to a design course")
        self.assertEqual(notes[0]["note_type"], "decision")
        self.assertEqual(notes[0]["title"], "Course")

    def test_confirm_matches_preview_with_appended_sections(self) -> None:
        """Endpoints may append expert-ideas markdown after the preview text."""
        preview = execute_tool_outcome(
            "add_client_note",
            {"client_id": "ali", "content": "Goal text", "note_type": "goal"},
            self.store,
        )
        history = [
            {"role": "assistant", "content": preview.text + "\n\n### Expert ideas\n- x"},
        ]
        pending = parse_pending_write(history)
        self.assertIsNotNone(pending)
        self.assertEqual(pending[0], "add_client_note")
        self.assertEqual(pending[1]["content"], "Goal text")

    def test_registry_replay_strips_confirmed_flag(self) -> None:
        register_pending_write("PREVIEW-TEXT", "delete_client_note",
                               {"note_id": 7, "confirmed": False})
        pending = parse_pending_write(
            [{"role": "assistant", "content": "PREVIEW-TEXT"}]
        )
        self.assertEqual(pending, ("delete_client_note", {"note_id": 7}))

    def test_legacy_regex_fallback_after_registry_loss(self) -> None:
        """A preview rendered before a restart still confirms via text parsing."""
        preview = execute_tool_outcome(
            "add_client_note",
            {"client_id": "ali", "content": "Persisted goal", "note_type": "goal"},
            self.store,
        )
        clear_pending_writes()  # simulate process restart
        history = [{"role": "assistant", "content": preview.text}]
        pending = parse_pending_write(history)
        self.assertIsNotNone(pending)
        self.assertEqual(pending[0], "add_client_note")
        self.assertEqual(pending[1]["content"], "Persisted goal")

    def test_cancellation_keeps_nothing_saved(self) -> None:
        preview = execute_tool_outcome(
            "delete_client", {"client_id": "ali"}, self.store
        )
        history = [{"role": "assistant", "content": preview.text}]
        result = try_direct_client_action_with_meta("no, cancel", self.store, history)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "ok")
        self.assertIsNotNone(self.store.get_user("ali"))


if __name__ == "__main__":
    unittest.main()
