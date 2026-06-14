"""Tests for LLM client-management tools."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.chat import reset_runtime_state, store
from app.core.confirmations import (
    is_user_cancellation,
    is_user_confirmation,
    parse_pending_write,
)
from app.core.llm import _generate_with_tools
from app.core.tools import TOOL_DEFINITIONS, execute_tool, sanitize_write_confirmation


class ExecuteToolTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime_state()

    def test_create_client_accepts_string_confirmed(self) -> None:
        result = execute_tool(
            "create_client",
            {
                "client_id": "hassan",
                "name": "Hassan",
                "confirmed": "true",
            },
            store,
        )
        self.assertIn("saved successfully", result)

    def test_create_client_requires_confirmation(self) -> None:
        result = execute_tool(
            "create_client",
            {
                "client_id": "ali",
                "name": "Ali Reza",
                "phone": "555-0100",
                "email": "ali@example.com",
            },
            store,
        )
        self.assertIn("pending confirmation", result)
        self.assertIn("Are you sure", result)
        self.assertIn("Email: ali@example.com", result)
        self.assertIsNone(store.get_user("ali"))

    def test_create_client_stores_profile_after_confirmation(self) -> None:
        args = {
            "client_id": "ali",
            "name": "Ali Reza",
            "phone": "555-0100",
            "email": "ali@example.com",
            "confirmed": True,
        }
        result = execute_tool("create_client", args, store)
        self.assertIn("saved successfully", result)
        user = store.get_user("ali")
        self.assertIsNotNone(user)
        self.assertEqual(user["name"], "Ali Reza")
        self.assertEqual(user["profile"]["phone"], "555-0100")

    def test_create_client_merges_existing_profile(self) -> None:
        base = {
            "client_id": "sara",
            "name": "Sara",
            "phone": "555-0100",
            "email": "sara@example.com",
            "confirmed": True,
        }
        execute_tool("create_client", base, store)
        execute_tool(
            "create_client",
            {
                "client_id": "sara",
                "name": "Sara",
                "phone": "555-9999",
                "confirmed": True,
            },
            store,
        )
        user = store.get_user("sara")
        self.assertEqual(user["profile"]["phone"], "555-9999")
        self.assertEqual(user["profile"]["email"], "sara@example.com")

    def test_update_client_alias_merges_profile(self) -> None:
        execute_tool(
            "create_client",
            {"client_id": "ali", "name": "Ali", "confirmed": True},
            store,
        )
        preview = execute_tool(
            "update_client",
            {"client_id": "ali", "age": 23},
            store,
        )
        self.assertIn("Update client", preview)
        self.assertIn("Age: 23", preview)
        execute_tool(
            "update_client",
            {"client_id": "ali", "age": 23, "confirmed": True},
            store,
        )
        user = store.get_user("ali")
        self.assertEqual(user["profile"]["age"], 23)

    def test_add_client_note_requires_existing_client(self) -> None:
        result = execute_tool(
            "add_client_note",
            {
                "client_id": "missing",
                "content": "Some note",
                "note_type": "general",
            },
            store,
        )
        self.assertIn("not found", result)

    def test_add_client_note_requires_confirmation(self) -> None:
        execute_tool(
            "create_client",
            {"client_id": "ali", "name": "Ali", "confirmed": True},
            store,
        )
        result = execute_tool(
            "add_client_note",
            {
                "client_id": "ali",
                "content": "Ali wants to change careers.",
                "note_type": "goal",
                "title": "Career goal",
            },
            store,
        )
        self.assertIn("pending confirmation", result)
        self.assertIn("Are you sure", result)
        self.assertIn("Ali wants to change careers.", result)
        self.assertEqual(len(store.get_client_notes("ali")), 0)

    def test_add_client_note_resolves_display_name(self) -> None:
        execute_tool(
            "create_client",
            {"client_id": "ali", "name": "Ali Reza", "confirmed": True},
            store,
        )
        result = execute_tool(
            "add_client_note",
            {
                "client_id": "Ali Reza",
                "content": "Wants to move abroad.",
                "confirmed": True,
            },
            store,
        )
        self.assertIn("added", result)
        self.assertEqual(len(store.get_client_notes("ali")), 1)

    def test_add_client_note_succeeds_after_confirmation(self) -> None:
        execute_tool(
            "create_client",
            {"client_id": "ali", "name": "Ali", "confirmed": True},
            store,
        )
        result = execute_tool(
            "add_client_note",
            {
                "client_id": "ali",
                "content": "Ali wants to change careers.",
                "note_type": "goal",
                "title": "Career goal",
                "confirmed": True,
            },
            store,
        )
        self.assertIn("added", result)
        notes = store.get_client_notes("ali", note_type="goal")
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["content"], "Ali wants to change careers.")

    def test_list_clients(self) -> None:
        execute_tool(
            "create_client",
            {"client_id": "ali", "name": "Ali", "confirmed": True},
            store,
        )
        result = execute_tool("list_clients", {}, store)
        self.assertIn("Ali", result)
        self.assertIn("ali", result)

    def test_list_clients_excludes_coach_session_user(self) -> None:
        from app.memory.session import SessionManager

        session_manager = SessionManager(store)
        session_manager.get_or_create_session_id(
            "coach-reza", coach_name="Reza Coach"
        )
        execute_tool(
            "create_client",
            {"client_id": "ali", "name": "Ali", "confirmed": True},
            store,
        )
        result = execute_tool("list_clients", {}, store)
        self.assertIn("Ali", result)
        self.assertNotIn("coach-reza", result)
        self.assertNotIn("Reza Coach", result)

    def test_get_client_returns_readable_profile(self) -> None:
        execute_tool(
            "create_client",
            {
                "client_id": "ali",
                "name": "Ali",
                "phone": "555",
                "email": "ali@example.com",
                "confirmed": True,
            },
            store,
        )
        result = execute_tool("get_client", {"client_id": "ali"}, store)
        self.assertIn("Name: Ali", result)
        self.assertIn("Phone: 555", result)
        self.assertIn("Email: ali@example.com", result)

    def test_get_client_resolves_display_name(self) -> None:
        execute_tool(
            "create_client",
            {
                "client_id": "ali",
                "name": "Ali Reza",
                "email": "ali@test.com",
                "confirmed": True,
            },
            store,
        )
        result = execute_tool("get_client", {"client_id": "Ali Reza"}, store)
        self.assertIn("Email: ali@test.com", result)

    def test_create_client_resolves_display_name_on_update(self) -> None:
        execute_tool(
            "create_client",
            {
                "client_id": "ali",
                "name": "Ali Reza",
                "email": "ali@example.com",
                "confirmed": True,
            },
            store,
        )
        preview = execute_tool(
            "create_client",
            {
                "client_id": "Ali Reza",
                "name": "Ali Reza",
                "phone": "555-9999",
            },
            store,
        )
        self.assertIn("pending confirmation", preview)
        saved = execute_tool(
            "create_client",
            {
                "client_id": "Ali Reza",
                "name": "Ali Reza",
                "phone": "555-9999",
                "confirmed": True,
            },
            store,
        )
        self.assertIn("saved successfully", saved)
        user = store.get_user("ali")
        self.assertEqual(user["profile"]["phone"], "555-9999")
        self.assertEqual(user["profile"]["email"], "ali@example.com")

    def test_list_client_notes(self) -> None:
        execute_tool(
            "create_client",
            {"client_id": "ali", "name": "Ali", "confirmed": True},
            store,
        )
        execute_tool(
            "add_client_note",
            {
                "client_id": "ali",
                "content": "Career change goal",
                "note_type": "goal",
                "confirmed": True,
            },
            store,
        )
        result = execute_tool(
            "list_client_notes",
            {"client_id": "ali", "note_type": "goal"},
            store,
        )
        self.assertIn("Career change goal", result)

    def test_update_client_note_requires_confirmation(self) -> None:
        execute_tool(
            "create_client",
            {"client_id": "ali", "name": "Ali", "confirmed": True},
            store,
        )
        add_result = execute_tool(
            "add_client_note",
            {
                "client_id": "ali",
                "content": "Original text",
                "note_type": "general",
                "confirmed": True,
            },
            store,
        )
        note_id = int(add_result.split("ID: ")[1].split(")")[0])
        preview = execute_tool(
            "update_client_note",
            {"note_id": note_id, "content": "Updated text"},
            store,
        )
        self.assertIn("pending confirmation", preview)
        saved = execute_tool(
            "update_client_note",
            {"note_id": note_id, "content": "Updated text", "confirmed": True},
            store,
        )
        self.assertIn("updated", saved)

    def test_delete_client_note_requires_confirmation(self) -> None:
        execute_tool(
            "create_client",
            {"client_id": "ali", "name": "Ali", "confirmed": True},
            store,
        )
        add_result = execute_tool(
            "add_client_note",
            {
                "client_id": "ali",
                "content": "To delete",
                "confirmed": True,
            },
            store,
        )
        note_id = int(add_result.split("ID: ")[1].split(")")[0])
        preview = execute_tool("delete_client_note", {"note_id": note_id}, store)
        self.assertIn("pending confirmation", preview)
        deleted = execute_tool(
            "delete_client_note",
            {"note_id": note_id, "confirmed": True},
            store,
        )
        self.assertIn("deleted", deleted)
        self.assertIsNone(store.get_client_note(note_id))

    def test_delete_client_requires_confirmation(self) -> None:
        execute_tool(
            "create_client",
            {"client_id": "ali", "name": "Ali", "confirmed": True},
            store,
        )
        preview = execute_tool("delete_client", {"client_id": "Ali"}, store)
        self.assertIn("pending confirmation", preview)
        deleted = execute_tool(
            "delete_client",
            {"client_id": "Ali", "confirmed": True},
            store,
        )
        self.assertIn("deleted", deleted)
        self.assertIsNone(store.get_user("ali"))

    def test_get_client_full_includes_notes(self) -> None:
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
        execute_tool(
            "add_client_note",
            {
                "client_id": "ali",
                "content": "Follow up about career change next week.",
                "note_type": "general",
                "confirmed": True,
            },
            store,
        )
        result = execute_tool("get_client_full", {"client_id": "ali"}, store)
        self.assertIn("Email: ali@example.com", result)
        self.assertIn("Follow up about career change next week.", result)


class ConfirmationTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime_state()

    def test_is_user_confirmation(self) -> None:
        self.assertTrue(is_user_confirmation("yes"))
        self.assertTrue(is_user_confirmation("confirm"))
        self.assertFalse(is_user_confirmation("add note for Ali"))

    def test_is_user_cancellation(self) -> None:
        for phrase in ("no", "No", "nope", "cancel", "don't save", "never mind"):
            self.assertTrue(is_user_cancellation(phrase), phrase)
        for phrase in ("yes", "confirm", "save it", "add note for Ali"):
            self.assertFalse(is_user_cancellation(phrase), phrase)

    def test_sanitize_write_confirmation_strips_premature_confirm(self) -> None:
        sanitized = sanitize_write_confirmation(
            "add_client_note",
            {
                "client_id": "ali",
                "content": "Test",
                "confirmed": True,
            },
            "Add a note for Ali: Test",
        )
        self.assertFalse(sanitized.get("confirmed"))

    def test_parse_pending_add_note_preview(self) -> None:
        execute_tool(
            "create_client",
            {"client_id": "mina", "name": "Mina", "confirmed": True},
            store,
        )
        preview = execute_tool(
            "add_client_note",
            {"client_id": "mina", "content": "She has two children"},
            store,
        )
        pending = parse_pending_write([{"role": "assistant", "content": preview}])
        self.assertEqual(
            pending,
            (
                "add_client_note",
                {
                    "client_id": "mina",
                    "content": "She has two children",
                    "note_type": "general",
                },
            ),
        )


class GenerateWithToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_write_preview_returns_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            test_store = type(store)(str(Path(tmp) / "test.db"))
            execute_tool(
                "create_client",
                {"client_id": "mina", "name": "Mina", "confirmed": True},
                test_store,
            )
            call_count = 0

            async def fake_post(_url: str, *, json: dict) -> MagicMock:
                nonlocal call_count
                call_count += 1
                body = {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "add_client_note",
                                    "arguments": {
                                        "client_id": "mina",
                                        "content": "She has two children",
                                        "confirmed": True,
                                    },
                                }
                            }
                        ],
                    }
                }
                response = MagicMock()
                response.raise_for_status = MagicMock()
                response.json = MagicMock(return_value=body)
                return response

            mock_client = MagicMock()
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            with patch("app.core.llm_providers.ollama.httpx.AsyncClient", return_value=mock_client):
                reply = await _generate_with_tools(
                    [
                        {
                            "role": "user",
                            "content": "Add note for Mina: she has two children",
                        }
                    ],
                    "system",
                    TOOL_DEFINITIONS,
                    test_store,
                )

            self.assertEqual(call_count, 1)
            self.assertIn("pending confirmation", reply)
            self.assertIn("She has two children", reply)
            self.assertEqual(len(test_store.get_client_notes("mina")), 0)

    async def test_text_tool_call_strips_premature_confirm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            test_store = type(store)(str(Path(tmp) / "test.db"))
            execute_tool(
                "create_client",
                {"client_id": "ali", "name": "Ali", "confirmed": True},
                test_store,
            )

            async def fake_post(_url: str, *, json: dict) -> MagicMock:
                body = {
                    "message": {
                        "role": "assistant",
                        "content": (
                            '{"tool": "create_client", "parameters": {'
                            '"client_id": "ali", "name": "Ali", '
                            '"phone": "9892323442", "confirmed": true}}'
                        ),
                    }
                }
                response = MagicMock()
                response.raise_for_status = MagicMock()
                response.json = MagicMock(return_value=body)
                return response

            mock_client = MagicMock()
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            with patch("app.core.llm_providers.ollama.httpx.AsyncClient", return_value=mock_client):
                reply = await _generate_with_tools(
                    [{"role": "user", "content": "set phone 9892323442"}],
                    "system",
                    TOOL_DEFINITIONS,
                    test_store,
                )

            self.assertIn("pending confirmation", reply)
            self.assertIn("9892323442", reply)
            user = test_store.get_user("ali")
            self.assertIsNone(user["profile"].get("phone"))

    async def test_profile_age_redirects_add_note_to_update_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            test_store = type(store)(str(Path(tmp) / "test.db"))
            execute_tool(
                "create_client",
                {"client_id": "ali", "name": "Ali", "confirmed": True},
                test_store,
            )

            async def fake_post(_url: str, *, json: dict) -> MagicMock:
                body = {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "add_client_note",
                                    "arguments": {
                                        "client_id": "ali",
                                        "content": "Ali is 23 years old",
                                        "note_type": "general",
                                    },
                                }
                            }
                        ],
                    }
                }
                response = MagicMock()
                response.raise_for_status = MagicMock()
                response.json = MagicMock(return_value=body)
                return response

            mock_client = MagicMock()
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            with patch("app.core.llm_providers.ollama.httpx.AsyncClient", return_value=mock_client):
                reply = await _generate_with_tools(
                    [{"role": "user", "content": "Ali is 23 years old"}],
                    "system",
                    TOOL_DEFINITIONS,
                    test_store,
                )

            self.assertIn("Update client", reply)
            self.assertIn("Age: 23", reply)
            self.assertNotIn("Add note", reply)
            self.assertEqual(len(test_store.get_client_notes("ali")), 0)

    async def test_coaching_advice_blocks_mistaken_add_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            test_store = type(store)(str(Path(tmp) / "test.db"))
            execute_tool(
                "create_client",
                {"client_id": "ali", "name": "Ali", "confirmed": True},
                test_store,
            )
            call_count = 0

            async def fake_post(_url: str, *, json: dict) -> MagicMock:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    body = {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "add_client_note",
                                        "arguments": {
                                            "client_id": "ali",
                                            "content": "Ask open-ended questions.",
                                            "note_type": "general",
                                        },
                                    }
                                }
                            ],
                        }
                    }
                else:
                    body = {
                        "message": {
                            "role": "assistant",
                            "content": (
                                "Try asking Ali what success would look like for him "
                                "this month, then explore one small step he could take."
                            ),
                        }
                    }
                response = MagicMock()
                response.raise_for_status = MagicMock()
                response.json = MagicMock(return_value=body)
                return response

            mock_client = MagicMock()
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            with patch("app.core.llm_providers.ollama.httpx.AsyncClient", return_value=mock_client):
                reply = await _generate_with_tools(
                    [
                        {
                            "role": "user",
                            "content": (
                                "In general I want to know one way about "
                                "make patient happier"
                            ),
                        }
                    ],
                    "system",
                    TOOL_DEFINITIONS,
                    test_store,
                )

            self.assertEqual(call_count, 2)
            self.assertNotIn("pending confirmation", reply)
            self.assertIn("success would look like", reply)
            self.assertEqual(len(test_store.get_client_notes("ali")), 0)

    async def test_user_yes_replays_pending_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            test_store = type(store)(str(Path(tmp) / "test.db"))
            execute_tool(
                "create_client",
                {"client_id": "mina", "name": "Mina", "confirmed": True},
                test_store,
            )
            preview = execute_tool(
                "add_client_note",
                {"client_id": "mina", "content": "She has two children"},
                test_store,
            )
            history = [
                {
                    "role": "user",
                    "content": "Add note for Mina: she has two children",
                },
                {"role": "assistant", "content": preview},
                {"role": "user", "content": "yes"},
            ]

            mock_client = MagicMock()
            mock_client.post = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            with patch("app.core.llm_providers.ollama.httpx.AsyncClient", return_value=mock_client):
                reply = await _generate_with_tools(
                    history,
                    "system",
                    TOOL_DEFINITIONS,
                    test_store,
                )

            mock_client.post.assert_not_called()
            self.assertIn("added for client", reply)
            notes = test_store.get_client_notes("mina")
            self.assertEqual(len(notes), 1)
            self.assertEqual(notes[0]["content"], "She has two children")

    async def test_user_no_cancels_pending_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            test_store = type(store)(str(Path(tmp) / "test.db"))
            execute_tool(
                "create_client",
                {"client_id": "mina", "name": "Mina", "confirmed": True},
                test_store,
            )
            preview = execute_tool(
                "add_client_note",
                {"client_id": "mina", "content": "She has two children"},
                test_store,
            )
            history = [
                {
                    "role": "user",
                    "content": "Add note for Mina: she has two children",
                },
                {"role": "assistant", "content": preview},
                {"role": "user", "content": "no"},
            ]

            mock_client = MagicMock()
            mock_client.post = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            with patch("app.core.llm_providers.ollama.httpx.AsyncClient", return_value=mock_client):
                reply = await _generate_with_tools(
                    history,
                    "system",
                    TOOL_DEFINITIONS,
                    test_store,
                )

            # The LLM must not be consulted and nothing should be saved or re-proposed.
            mock_client.post.assert_not_called()
            self.assertNotIn("pending confirmation", reply)
            self.assertIn("won't save", reply)
            self.assertEqual(len(test_store.get_client_notes("mina")), 0)

    async def test_tool_results_include_tool_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            test_store = type(store)(str(Path(tmp) / "test.db"))
            captured_payloads: list[dict] = []

            async def fake_post(_url: str, *, json: dict) -> MagicMock:
                captured_payloads.append(json)
                if len(captured_payloads) == 1:
                    body = {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "list_clients",
                                        "arguments": {},
                                    }
                                }
                            ],
                        }
                    }
                else:
                    body = {
                        "message": {
                            "role": "assistant",
                            "content": "You have no clients yet.",
                        }
                    }
                response = MagicMock()
                response.raise_for_status = MagicMock()
                response.json = MagicMock(return_value=body)
                return response

            mock_client = MagicMock()
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            with patch("app.core.llm_providers.ollama.httpx.AsyncClient", return_value=mock_client):
                reply = await _generate_with_tools(
                    [{"role": "user", "content": "Use the registry tool."}],
                    "system",
                    TOOL_DEFINITIONS,
                    test_store,
                )

            self.assertEqual(reply, "You have no clients yet.")
            tool_messages = [
                m
                for m in captured_payloads[1]["messages"]
                if m.get("role") == "tool"
            ]
            self.assertEqual(len(tool_messages), 1)
            self.assertEqual(tool_messages[0]["tool_name"], "list_clients")

if __name__ == "__main__":
    unittest.main()
