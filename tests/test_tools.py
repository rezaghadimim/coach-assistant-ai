"""Tests for LLM client-management tools."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.chat import reset_runtime_state, store
from app.core.llm import _generate_with_tools
from app.core.tools import TOOL_DEFINITIONS, execute_tool


class ExecuteToolTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime_state()

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


class GenerateWithToolsTests(unittest.IsolatedAsyncioTestCase):
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

            with patch("app.core.llm.httpx.AsyncClient", return_value=mock_client):
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

    async def test_client_mention_injects_context_into_system_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            test_store = type(store)(str(Path(tmp) / "test.db"))
            execute_tool(
                "create_client",
                {
                    "client_id": "ali",
                    "name": "Ali",
                    "email": "ali@example.com",
                    "confirmed": True,
                },
                test_store,
            )
            captured_payloads: list[dict] = []

            async def fake_post(_url: str, *, json: dict) -> MagicMock:
                captured_payloads.append(json)
                body = {
                    "message": {
                        "role": "assistant",
                        "content": "Focus on Ali's stated goals and check in on progress.",
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

            with patch("app.core.llm.httpx.AsyncClient", return_value=mock_client):
                reply = await _generate_with_tools(
                    [
                        {
                            "role": "user",
                            "content": "How can we best support Ali today?",
                        }
                    ],
                    "system",
                    TOOL_DEFINITIONS,
                    test_store,
                )

            self.assertIn("Focus on Ali's stated goals", reply)
            system_prompt = captured_payloads[0]["messages"][0]["content"]
            self.assertIn("Referenced Client Record", system_prompt)
            self.assertIn("Email: ali@example.com", system_prompt)


if __name__ == "__main__":
    unittest.main()
