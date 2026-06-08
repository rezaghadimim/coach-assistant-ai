"""Phase 4 tests: Open WebUI / OpenAI-compatible API."""

import json
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.api.chat import reset_runtime_state
from main import app


class Phase4OpenAICompatTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime_state()
        self.client = TestClient(app)

    # ------------------------------------------------------------------
    # /v1/models
    # ------------------------------------------------------------------

    def test_list_models_returns_coach_assistant_entry(self) -> None:
        response = self.client.get("/v1/models")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["object"], "list")
        ids = [m["id"] for m in body["data"]]
        self.assertIn("coach-assistant-ai", ids)

    # ------------------------------------------------------------------
    # /v1/chat/completions — non-streaming
    # ------------------------------------------------------------------

    def test_chat_completion_non_streaming_returns_openai_shape(self) -> None:
        with patch(
            "app.api.openai_compat.generate_response",
            new=AsyncMock(return_value="What goal would you like to focus on?"),
        ):
            response = self.client.post(
                "/v1/chat/completions",
                json={
                    "model": "coach-assistant-ai",
                    "messages": [{"role": "user", "content": "I need help with focus."}],
                    "stream": False,
                    "user": "test-user",
                },
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["object"], "chat.completion")
        self.assertEqual(body["model"], "coach-assistant-ai")
        self.assertEqual(len(body["choices"]), 1)
        choice = body["choices"][0]
        self.assertEqual(choice["message"]["role"], "assistant")
        self.assertEqual(
            choice["message"]["content"],
            "What goal would you like to focus on?",
        )
        self.assertEqual(choice["finish_reason"], "stop")

    def test_chat_completion_uses_x_user_id_header(self) -> None:
        with patch(
            "app.api.openai_compat.generate_response",
            new=AsyncMock(return_value="Tell me more about your situation."),
        ):
            response = self.client.post(
                "/v1/chat/completions",
                json={
                    "model": "coach-assistant-ai",
                    "messages": [{"role": "user", "content": "Help me plan my week."}],
                },
                headers={"X-User-Id": "header-user"},
            )
        self.assertEqual(response.status_code, 200)

    def test_chat_completion_defaults_to_openwebui_user(self) -> None:
        with patch(
            "app.api.openai_compat.generate_response",
            new=AsyncMock(return_value="Let's explore your options."),
        ):
            response = self.client.post(
                "/v1/chat/completions",
                json={
                    "model": "coach-assistant-ai",
                    "messages": [{"role": "user", "content": "Hello"}],
                },
            )
        self.assertEqual(response.status_code, 200)

    def test_chat_completion_persists_messages_in_session(self) -> None:
        from app.api.chat import store, session_manager

        with patch(
            "app.api.openai_compat.generate_response",
            new=AsyncMock(return_value="Great, what would success look like?"),
        ):
            self.client.post(
                "/v1/chat/completions",
                json={
                    "model": "coach-assistant-ai",
                    "messages": [
                        {"role": "user", "content": "I want to improve my productivity."}
                    ],
                    "user": "persist-user",
                },
            )

        session_id = session_manager.get_or_create_session_id("persist-user")
        messages = store.get_session_messages(session_id)
        roles = [m["role"] for m in messages]
        self.assertIn("user", roles)
        self.assertIn("assistant", roles)

    # ------------------------------------------------------------------
    # /v1/chat/completions — streaming
    # ------------------------------------------------------------------

    def test_chat_completion_streaming_returns_sse_events(self) -> None:
        with patch(
            "app.api.openai_compat.generate_response",
            new=AsyncMock(return_value="Hello there!"),
        ):
            response = self.client.post(
                "/v1/chat/completions",
                json={
                    "model": "coach-assistant-ai",
                    "messages": [{"role": "user", "content": "Hi"}],
                    "stream": True,
                    "user": "stream-user",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers.get("content-type", ""))
        lines = [line for line in response.text.splitlines() if line.startswith("data:")]
        self.assertTrue(any("chat.completion.chunk" in line for line in lines))
        self.assertTrue(any("[DONE]" in line for line in lines))

    def test_chat_completion_streaming_chunks_contain_content(self) -> None:
        with patch(
            "app.api.openai_compat.generate_response",
            new=AsyncMock(return_value="Think about your goal."),
        ):
            response = self.client.post(
                "/v1/chat/completions",
                json={
                    "model": "coach-assistant-ai",
                    "messages": [{"role": "user", "content": "What should I do?"}],
                    "stream": True,
                    "user": "chunk-user",
                },
            )

        data_lines = [
            line[len("data: "):].strip()
            for line in response.text.splitlines()
            if line.startswith("data:") and "[DONE]" not in line
        ]
        content_tokens = []
        for raw in data_lines:
            chunk = json.loads(raw)
            for choice in chunk.get("choices", []):
                token = choice.get("delta", {}).get("content")
                if token:
                    content_tokens.append(token)
        self.assertEqual("".join(content_tokens), "Think about your goal.")


if __name__ == "__main__":
    unittest.main()
