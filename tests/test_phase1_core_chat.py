"""Phase 1 core chat tests."""

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.api.chat import _sessions, reset_runtime_state
from app.rag.retriever import clear_index
from main import app


class Phase1CoreChatTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime_state()
        clear_index()
        _sessions.clear()
        self.client = TestClient(app)

    def test_health_endpoint_returns_status_and_model(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertIn("providers", body)
        self.assertIn("ollama", body["providers"])
        self.assertTrue(body["providers"]["ollama"]["model"])

    def test_chat_returns_llm_reply(self) -> None:
        with patch(
            "app.api.chat.generate_response",
            new=AsyncMock(return_value="Let's define a concrete next action."),
        ) as mocked_generate:
            response = self.client.post(
                "/api/chat",
                json={"user_id": "client-1", "message": "I want to improve focus."},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "user_id": "client-1",
                "message": "I want to improve focus.",
                "reply": "Let's define a concrete next action.",
                "expert_ideas": [],
            },
        )
        mocked_generate.assert_awaited_once()
        called_messages = mocked_generate.await_args.kwargs["messages"]
        self.assertEqual(
            called_messages[0], {"role": "user", "content": "I want to improve focus."}
        )

    def test_chat_preserves_per_user_history(self) -> None:
        captured_messages = []

        async def _fake_generate(messages, **_kwargs):
            captured_messages.append([message.copy() for message in messages])
            return (
                "First coach reply."
                if len(captured_messages) == 1
                else "Second coach reply."
            )

        with patch(
            "app.api.chat.generate_response",
            new=AsyncMock(side_effect=_fake_generate),
        ):
            self.client.post(
                "/api/chat",
                json={"user_id": "client-2", "message": "Session start"},
            )
            response = self.client.post(
                "/api/chat",
                json={"user_id": "client-2", "message": "Follow-up question"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reply"], "Second coach reply.")
        second_call_messages = captured_messages[1]
        self.assertEqual(
            second_call_messages,
            [
                {"role": "user", "content": "Session start"},
                {"role": "assistant", "content": "First coach reply."},
                {"role": "user", "content": "Follow-up question"},
            ],
        )

    def test_chat_returns_502_when_llm_fails(self) -> None:
        with patch(
            "app.api.chat.generate_response",
            new=AsyncMock(side_effect=RuntimeError("ollama unavailable")),
        ):
            response = self.client.post(
                "/api/chat",
                json={"user_id": "client-3", "message": "Can we continue?"},
            )

        self.assertEqual(response.status_code, 502)
        self.assertIn("LLM service error", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
