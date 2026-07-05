"""Tests for client notes (documentation, stories, decisions) endpoints."""

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.api.chat import reset_runtime_state
from main import app


class ClientNotesTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime_state()
        self.client = TestClient(app)
        # Create a user first
        self.client.post(
            "/api/users",
            json={
                "user_id": "client-1",
                "name": "Alice",
                "profile": {"goals": ["Career change"]},
            },
        )

    # ------------------------------------------------------------------
    # Create notes
    # ------------------------------------------------------------------

    def test_create_general_note(self) -> None:
        response = self.client.post(
            "/api/clients/client-1/notes",
            json={
                "user_id": "client-1",
                "content": "Alice expressed frustration with current job.",
                "note_type": "general",
                "title": "Initial Assessment",
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["user_id"], "client-1")
        self.assertEqual(body["note_type"], "general")
        self.assertEqual(body["title"], "Initial Assessment")
        self.assertIn("frustration", body["content"])

    def test_create_story_note(self) -> None:
        response = self.client.post(
            "/api/clients/client-1/notes",
            json={
                "user_id": "client-1",
                "content": "Alice shared that she grew up wanting to be an artist.",
                "note_type": "story",
                "title": "Background Story",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["note_type"], "story")

    def test_create_decision_note(self) -> None:
        response = self.client.post(
            "/api/clients/client-1/notes",
            json={
                "user_id": "client-1",
                "content": "Alice decided to enroll in a design course.",
                "note_type": "decision",
                "title": "Career Decision",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["note_type"], "decision")

    def test_create_note_for_missing_client_returns_404(self) -> None:
        response = self.client.post(
            "/api/clients/nonexistent/notes",
            json={
                "user_id": "nonexistent",
                "content": "Some note",
            },
        )
        self.assertEqual(response.status_code, 404)

    # ------------------------------------------------------------------
    # List notes
    # ------------------------------------------------------------------

    def test_list_notes_returns_all(self) -> None:
        self.client.post(
            "/api/clients/client-1/notes",
            json={"user_id": "client-1", "content": "Note 1", "note_type": "general"},
        )
        self.client.post(
            "/api/clients/client-1/notes",
            json={"user_id": "client-1", "content": "Note 2", "note_type": "decision"},
        )

        response = self.client.get("/api/clients/client-1/notes")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["notes"]), 2)

    def test_list_notes_filter_by_type(self) -> None:
        self.client.post(
            "/api/clients/client-1/notes",
            json={"user_id": "client-1", "content": "Story 1", "note_type": "story"},
        )
        self.client.post(
            "/api/clients/client-1/notes",
            json={"user_id": "client-1", "content": "Decision 1", "note_type": "decision"},
        )

        response = self.client.get("/api/clients/client-1/notes?note_type=story")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["notes"]), 1)
        self.assertEqual(body["notes"][0]["note_type"], "story")

    # ------------------------------------------------------------------
    # Update notes
    # ------------------------------------------------------------------

    def test_update_note(self) -> None:
        create_resp = self.client.post(
            "/api/clients/client-1/notes",
            json={
                "user_id": "client-1",
                "content": "Initial decision: start freelancing",
                "note_type": "decision",
                "title": "Career Decision",
            },
        )
        note_id = create_resp.json()["id"]

        update_resp = self.client.put(
            f"/api/clients/client-1/notes/{note_id}",
            json={
                "content": "Updated decision: start freelancing part-time first",
                "title": "Career Decision (Revised)",
            },
        )
        self.assertEqual(update_resp.status_code, 200)
        body = update_resp.json()
        self.assertIn("part-time", body["content"])
        self.assertIn("Revised", body["title"])

    def test_update_nonexistent_note_returns_404(self) -> None:
        response = self.client.put(
            "/api/clients/client-1/notes/9999",
            json={"content": "Updated content"},
        )
        self.assertEqual(response.status_code, 404)

    # ------------------------------------------------------------------
    # Delete notes
    # ------------------------------------------------------------------

    def test_delete_note(self) -> None:
        create_resp = self.client.post(
            "/api/clients/client-1/notes",
            json={"user_id": "client-1", "content": "To be deleted"},
        )
        note_id = create_resp.json()["id"]

        delete_resp = self.client.delete(f"/api/clients/client-1/notes/{note_id}")
        self.assertEqual(delete_resp.status_code, 200)

        # Verify it's gone
        list_resp = self.client.get("/api/clients/client-1/notes")
        self.assertEqual(len(list_resp.json()["notes"]), 0)

    def test_delete_nonexistent_note_returns_404(self) -> None:
        response = self.client.delete("/api/clients/client-1/notes/9999")
        self.assertEqual(response.status_code, 404)

    # ------------------------------------------------------------------
    # Notes injected into chat context
    # ------------------------------------------------------------------

    def test_client_notes_appear_in_system_prompt(self) -> None:
        # Create a note
        self.client.post(
            "/api/clients/client-1/notes",
            json={
                "user_id": "client-1",
                "content": "Alice wants to transition to UX design",
                "note_type": "goal",
                "title": "Career Goal",
            },
        )

        with patch(
            "app.api.chat.generate_response",
            new=AsyncMock(return_value="Let's build on your UX goal."),
        ) as mocked:
            self.client.post(
                "/api/chat",
                json={"user_id": "client-1", "message": "What should I focus on?"},
            )
            system_prompt = mocked.await_args.kwargs["system_prompt"]
            self.assertIn("Client Documentation", system_prompt)
            self.assertIn("UX design", system_prompt)


if __name__ == "__main__":
    unittest.main()
