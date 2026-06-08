"""Tests for LLM client-management tools."""

import json
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

    def test_create_client_stores_profile(self) -> None:
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
        self.assertIn("saved successfully", result)
        user = store.get_user("ali")
        self.assertIsNotNone(user)
        self.assertEqual(user["name"], "Ali Reza")
        self.assertEqual(user["profile"]["phone"], "555-0100")

    def test_create_client_merges_existing_profile(self) -> None:
        execute_tool(
            "create_client",
            {
                "client_id": "sara",
                "name": "Sara",
                "phone": "555-0100",
                "email": "sara@example.com",
            },
            store,
        )
        execute_tool(
            "create_client",
            {"client_id": "sara", "name": "Sara", "phone": "555-9999"},
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

    def test_add_client_note_succeeds(self) -> None:
        execute_tool(
            "create_client",
            {"client_id": "ali", "name": "Ali"},
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
        self.assertIn("added", result)
        notes = store.get_client_notes("ali", note_type="goal")
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["content"], "Ali wants to change careers.")

    def test_list_clients(self) -> None:
        execute_tool(
            "create_client",
            {"client_id": "ali", "name": "Ali"},
            store,
        )
        result = execute_tool("list_clients", {}, store)
        self.assertIn("Ali", result)
        self.assertIn("ali", result)

    def test_get_client_returns_json(self) -> None:
        execute_tool(
            "create_client",
            {"client_id": "ali", "name": "Ali", "phone": "555"},
            store,
        )
        result = execute_tool("get_client", {"client_id": "ali"}, store)
        data = json.loads(result)
        self.assertEqual(data["name"], "Ali")
        self.assertEqual(data["profile"]["phone"], "555")


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
                    [{"role": "user", "content": "Who are my clients?"}],
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
