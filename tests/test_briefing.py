"""Tests for POST /api/briefing — structured coaching case briefing endpoint."""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.api.chat import reset_runtime_state
from app.models.schemas import CoachBriefing
from main import app


VALID_BRIEFING = {
    "key_insights": ["Client appears stuck in all-or-nothing thinking."],
    "hypotheses": ["The pattern may stem from a fear of failure."],
    "coaching_questions": [
        "What would partial success look like?",
        "When did you last feel confident — what was different then?",
    ],
    "recommended_framework": "CBT-informed",
    "framework_rationale": "The client's language suggests cognitive distortions that CBT tools can address.",
    "action_plan": ["Explore the evidence for and against the limiting belief.", "Design a small behavioural experiment."],
    "homework": ["Complete a thought record when the pattern arises this week."],
}


class TestBriefingEndpoint(unittest.TestCase):

    def setUp(self) -> None:
        reset_runtime_state()
        self.client = TestClient(app)

    def _mock_llm(self, content: str):
        fake_result = MagicMock()
        fake_result.content = content
        return AsyncMock(return_value=fake_result)

    def test_briefing_returns_valid_schema(self) -> None:
        with patch(
            "app.api.briefing.OllamaProvider",
        ) as MockProvider:
            instance = MockProvider.return_value
            instance.complete = self._mock_llm(json.dumps(VALID_BRIEFING))
            resp = self.client.post(
                "/api/briefing",
                json={"user_id": "coach-1", "question": "My client is stuck with procrastination."},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        briefing = CoachBriefing(**body)
        self.assertIsInstance(briefing.key_insights, list)
        self.assertIsInstance(briefing.coaching_questions, list)
        self.assertGreater(len(briefing.coaching_questions), 0)
        self.assertEqual(briefing.recommended_framework, "CBT-informed")

    def test_briefing_strips_markdown_code_fences(self) -> None:
        wrapped = f"```json\n{json.dumps(VALID_BRIEFING)}\n```"
        with patch(
            "app.api.briefing.OllamaProvider",
        ) as MockProvider:
            instance = MockProvider.return_value
            instance.complete = self._mock_llm(wrapped)
            resp = self.client.post(
                "/api/briefing",
                json={"user_id": "coach-1", "question": "Client is anxious about a presentation."},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["recommended_framework"], "CBT-informed")

    def test_briefing_returns_502_on_invalid_json(self) -> None:
        with patch(
            "app.api.briefing.OllamaProvider",
        ) as MockProvider:
            instance = MockProvider.return_value
            instance.complete = self._mock_llm("This is not JSON at all.")
            resp = self.client.post(
                "/api/briefing",
                json={"user_id": "coach-1", "question": "Something."},
            )

        self.assertEqual(resp.status_code, 502)

    def test_briefing_returns_502_on_llm_error(self) -> None:
        with patch(
            "app.api.briefing.OllamaProvider",
        ) as MockProvider:
            instance = MockProvider.return_value
            instance.complete = AsyncMock(side_effect=ConnectionError("Ollama down"))
            resp = self.client.post(
                "/api/briefing",
                json={"user_id": "coach-1", "question": "Something."},
            )

        self.assertEqual(resp.status_code, 502)

    def test_briefing_requires_question(self) -> None:
        resp = self.client.post(
            "/api/briefing",
            json={"user_id": "coach-1"},
        )
        self.assertEqual(resp.status_code, 422)

    def test_briefing_requires_user_id(self) -> None:
        resp = self.client.post(
            "/api/briefing",
            json={"question": "My client is stuck."},
        )
        self.assertEqual(resp.status_code, 422)

    def test_briefing_with_client_id_includes_notes_context(self) -> None:
        """When client_id is given, client notes are loaded for context."""
        with (
            patch("app.api.briefing._store") as mock_store,
            patch("app.api.briefing.OllamaProvider") as MockProvider,
        ):
            mock_store.get_client_notes.return_value = [
                {
                    "note_type": "goal",
                    "title": "Career change",
                    "content": "Client wants to move from finance to coaching.",
                    "updated_at": "2026-01-01",
                }
            ]
            instance = MockProvider.return_value
            instance.complete = self._mock_llm(json.dumps(VALID_BRIEFING))
            resp = self.client.post(
                "/api/briefing",
                json={
                    "user_id": "coach-1",
                    "client_id": "client-42",
                    "question": "How should I structure today's session?",
                },
            )

        self.assertEqual(resp.status_code, 200)
        # Verify the LLM received client notes in context
        call_args = instance.complete.await_args
        user_message = call_args[0][0][1]["content"]
        self.assertIn("Career change", user_message)


class TestCoachBriefingSchema(unittest.TestCase):
    """Unit tests for the CoachBriefing Pydantic model."""

    def test_default_empty_lists(self) -> None:
        briefing = CoachBriefing()
        self.assertEqual(briefing.key_insights, [])
        self.assertEqual(briefing.coaching_questions, [])
        self.assertEqual(briefing.homework, [])
        self.assertEqual(briefing.recommended_framework, "")

    def test_full_briefing_roundtrip(self) -> None:
        briefing = CoachBriefing(**VALID_BRIEFING)
        data = briefing.model_dump()
        briefing2 = CoachBriefing(**data)
        self.assertEqual(briefing, briefing2)


if __name__ == "__main__":
    unittest.main()
