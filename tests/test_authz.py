"""Authentication and authorization regression tests (SEC-01, SEC-02, TEST-04)."""

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.api.chat import reset_runtime_state, store
from app.core.config import settings
from main import app

API_KEY = "test-secret-key"


class ApiKeyAuthTests(unittest.TestCase):
    """Every router rejects requests without the configured API key."""

    def setUp(self) -> None:
        reset_runtime_state()
        self.client = TestClient(app)
        self._old_key = settings.api_key
        self._old_debug = settings.debug
        settings.api_key = API_KEY
        settings.debug = False

    def tearDown(self) -> None:
        settings.api_key = self._old_key
        settings.debug = self._old_debug

    def test_chat_without_key_is_401(self) -> None:
        response = self.client.post(
            "/api/chat", json={"user_id": "u1", "message": "hello"}
        )
        self.assertEqual(response.status_code, 401)

    def test_chat_with_key_succeeds(self) -> None:
        with patch(
            "app.api.chat.generate_response",
            new=AsyncMock(return_value="Hi there"),
        ):
            response = self.client.post(
                "/api/chat",
                json={"user_id": "u1", "message": "hello"},
                headers={"X-API-Key": API_KEY},
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["reply"])

    def test_bearer_token_accepted(self) -> None:
        response = self.client.get(
            "/api/users/nope", headers={"Authorization": f"Bearer {API_KEY}"}
        )
        # Authenticated; 404 because the user does not exist (not 401).
        self.assertEqual(response.status_code, 404)

    def test_wrong_key_is_401(self) -> None:
        response = self.client.get(
            "/api/users/nope", headers={"X-API-Key": "wrong"}
        )
        self.assertEqual(response.status_code, 401)

    def test_all_routers_reject_missing_key(self) -> None:
        cases = [
            ("post", "/api/chat", {"user_id": "u1", "message": "hi"}),
            ("post", "/api/users", {"user_id": "u1"}),
            ("get", "/api/users/u1", None),
            ("get", "/api/sessions/u1", None),
            ("get", "/api/clients/u1/notes", None),
            ("get", "/api/collections", None),
            ("get", "/v1/models", None),
        ]
        for method, url, body in cases:
            with self.subTest(url=url):
                response = getattr(self.client, method)(
                    url, **({"json": body} if body is not None else {})
                )
                self.assertEqual(response.status_code, 401, url)

    def test_health_endpoints_stay_open(self) -> None:
        self.assertEqual(self.client.get("/health/live").status_code, 200)

    def test_fails_closed_without_key_outside_debug(self) -> None:
        settings.api_key = ""
        settings.debug = False
        response = self.client.get("/api/users/u1")
        self.assertEqual(response.status_code, 401)

    def test_debug_mode_allows_missing_key(self) -> None:
        settings.api_key = ""
        settings.debug = True
        response = self.client.get("/api/users/nope")
        self.assertEqual(response.status_code, 404)


class NoteOwnershipTests(unittest.TestCase):
    """Cross-tenant note update/delete must 404 and leave the note unchanged."""

    def setUp(self) -> None:
        reset_runtime_state()
        self.client = TestClient(app)
        for user_id, name in (("a", "Alice"), ("b", "Bob")):
            self.client.post("/api/users", json={"user_id": user_id, "name": name})
        response = self.client.post(
            "/api/clients/a/notes",
            json={"user_id": "a", "content": "Alice's private note"},
        )
        self.note_id = response.json()["id"]

    def test_cross_user_delete_returns_404_and_keeps_note(self) -> None:
        response = self.client.delete(f"/api/clients/b/notes/{self.note_id}")
        self.assertEqual(response.status_code, 404)
        note = store.get_client_note(self.note_id)
        self.assertIsNotNone(note)
        self.assertEqual(note["user_id"], "a")

    def test_cross_user_update_returns_404_and_keeps_content(self) -> None:
        response = self.client.put(
            f"/api/clients/b/notes/{self.note_id}",
            json={"content": "hijacked"},
        )
        self.assertEqual(response.status_code, 404)
        note = store.get_client_note(self.note_id)
        self.assertEqual(note["content"], "Alice's private note")

    def test_owner_update_and_delete_still_work(self) -> None:
        response = self.client.put(
            f"/api/clients/a/notes/{self.note_id}",
            json={"content": "updated by owner"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["content"], "updated by owner")
        response = self.client.delete(f"/api/clients/a/notes/{self.note_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(store.get_client_note(self.note_id))


if __name__ == "__main__":
    unittest.main()
