"""Phase 3 tests: SQLite memory and session lifecycle."""

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.api.chat import reset_runtime_state, session_manager, store
from main import app


class Phase3MemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime_state()
        self.client = TestClient(app)

    def test_user_create_and_read_endpoints(self) -> None:
        create_response = self.client.post(
            "/api/users",
            json={
                "user_id": "memory-user",
                "name": "Ava",
                "profile": {"goals": ["Improve focus"]},
            },
        )
        self.assertEqual(create_response.status_code, 200)

        get_response = self.client.get("/api/users/memory-user")
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.json()["name"], "Ava")
        self.assertEqual(get_response.json()["profile"]["goals"], ["Improve focus"])

    def test_new_session_endpoint_closes_previous_session_with_summary(self) -> None:
        with patch(
            "app.api.chat.generate_response",
            new=AsyncMock(return_value="What would progress look like this week?"),
        ):
            self.client.post(
                "/api/chat",
                json={"user_id": "session-user", "message": "I need accountability"},
            )

        previous_session = session_manager.get_or_create_session_id("session-user")
        response = self.client.post("/api/sessions/session-user/new")
        self.assertEqual(response.status_code, 200)

        sessions = store.list_sessions("session-user")
        closed_previous = next(session for session in sessions if session["session_id"] == previous_session)
        self.assertIsNotNone(closed_previous["ended_at"])
        self.assertTrue(closed_previous["summary"])

    def test_session_history_endpoint_lists_persisted_sessions(self) -> None:
        with patch(
            "app.api.chat.generate_response",
            new=AsyncMock(return_value="Let's break that into two actions."),
        ):
            self.client.post(
                "/api/chat",
                json={"user_id": "history-user", "message": "I feel overwhelmed"},
            )
            self.client.post("/api/sessions/history-user/new")

        response = self.client.get("/api/sessions/history-user")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["user_id"], "history-user")
        self.assertGreaterEqual(len(body["sessions"]), 1)


if __name__ == "__main__":
    unittest.main()
