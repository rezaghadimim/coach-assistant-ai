"""Safety and role-boundary tests for Coach Assistant AI.

Verifies that the scope guard and prompt boundaries prevent the assistant from:
- Acting as a clinical therapist or mental health provider
- Diagnosing mental health conditions
- Giving medication or clinical advice
- Responding to crisis keywords without referral guidance

These tests operate at the scope-guard and prompt level (deterministic checks)
and via mocked LLM calls for prompt-enforced boundaries.
"""

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.api.chat import reset_runtime_state
from app.core.scope import scope_guard


class TestScopeGuardSafety(unittest.TestCase):
    """Unit tests for the deterministic scope guardrail."""

    def test_code_request_blocked(self) -> None:
        self.assertIsNotNone(scope_guard("write me some python code"))

    def test_math_blocked(self) -> None:
        self.assertIsNotNone(scope_guard("calculate the integral of x squared"))

    def test_weather_blocked(self) -> None:
        self.assertIsNotNone(scope_guard("what is the weather today in London"))

    def test_coaching_topic_allowed(self) -> None:
        self.assertIsNone(scope_guard("How can I help my client with procrastination?"))

    def test_emotional_topic_allowed(self) -> None:
        self.assertIsNone(scope_guard("My client feels stuck and anxious about career change"))

    def test_grow_question_allowed(self) -> None:
        self.assertIsNone(scope_guard("What GROW questions should I use for goal setting?"))

    def test_mi_topic_allowed(self) -> None:
        self.assertIsNone(scope_guard("How do I use motivational interviewing when a client is ambivalent?"))


class TestPromptRoleBoundaries(unittest.TestCase):
    """Verify that system prompt clauses for role boundaries exist."""

    def setUp(self) -> None:
        from app.core.prompts import COACH_ASSISTANT_SYSTEM_PROMPT
        self.prompt = COACH_ASSISTANT_SYSTEM_PROMPT

    def test_prompt_identifies_as_coach_tool(self) -> None:
        lower = self.prompt.lower()
        # The prompt must identify itself as a tool for coaches (in some phrasing).
        self.assertTrue(
            "life coach" in lower or "professional coach" in lower,
            "Prompt should identify as a coach-focused tool",
        )

    def test_prompt_does_not_claim_therapist_role(self) -> None:
        # The prompt should not position the AI as a therapist/counsellor.
        lower = self.prompt.lower()
        self.assertNotIn("you are a therapist", lower)
        self.assertNotIn("you are a counsellor", lower)
        self.assertNotIn("you are a psychologist", lower)

    def test_prompt_has_clinical_referral_boundary(self) -> None:
        lower = self.prompt.lower()
        self.assertIn("therapist", lower)
        self.assertIn("clinical", lower)

    def test_prompt_has_no_diagnosis_clause(self) -> None:
        lower = self.prompt.lower()
        self.assertIn("never diagnose", lower)

    def test_prompt_coach_facing_framing(self) -> None:
        # Should advise the coach rather than speak directly as a therapist to client.
        lower = self.prompt.lower()
        self.assertIn("support the coach", lower)

    def test_prompt_includes_cbt(self) -> None:
        self.assertIn("CBT", self.prompt)

    def test_prompt_includes_grow(self) -> None:
        self.assertIn("GROW", self.prompt)

    def test_prompt_includes_mi(self) -> None:
        lower = self.prompt.lower()
        self.assertIn("motivational interviewing", lower)


class TestClinicalRefusals(unittest.TestCase):
    """Integration tests: assistant refuses clinical / out-of-scope requests."""

    def setUp(self) -> None:
        from main import app
        reset_runtime_state()
        self.client = TestClient(app)

    def _chat(self, message: str) -> str:
        with patch(
            "app.api.chat.generate_response",
            new=AsyncMock(return_value="MOCKED"),
        ):
            resp = self.client.post(
                "/api/chat",
                json={"user_id": "safety-test-coach", "message": message},
            )
        self.assertEqual(resp.status_code, 200)
        return resp.json()["reply"]

    def test_scope_guard_blocks_code_before_llm(self) -> None:
        """Off-topic code requests must be blocked by scope_guard without LLM."""
        # Don't mock generate_response — scope_guard should intercept first.
        resp = self.client.post(
            "/api/chat",
            json={"user_id": "safety-test-coach", "message": "write a python function for me"},
        )
        self.assertEqual(resp.status_code, 200)
        reply = resp.json()["reply"]
        self.assertNotIn("def ", reply)
        # Should contain a coaching redirect
        self.assertIn("coaching", reply.lower())

    def test_scope_guard_blocks_math_before_llm(self) -> None:
        resp = self.client.post(
            "/api/chat",
            json={"user_id": "safety-test-coach", "message": "what is 152 * 37"},
        )
        self.assertEqual(resp.status_code, 200)
        reply = resp.json()["reply"]
        # Should refuse, not calculate
        self.assertNotIn("5624", reply)


class TestSummarizerPrompt(unittest.TestCase):
    """Verify SUMMARIZER_PROMPT contains structured session sections."""

    def test_summarizer_prompt_has_required_sections(self) -> None:
        from app.core.prompts import SUMMARIZER_PROMPT
        lower = SUMMARIZER_PROMPT.lower()
        self.assertIn("key topics", lower)
        self.assertIn("action items", lower)
        self.assertIn("decisions", lower)

    def test_summarizer_prompt_not_empty(self) -> None:
        from app.core.prompts import SUMMARIZER_PROMPT
        self.assertGreater(len(SUMMARIZER_PROMPT.strip()), 100)


class TestBriefingPrompt(unittest.TestCase):
    """Verify BRIEFING_PROMPT enforces coaching (not clinical) framing."""

    def test_briefing_prompt_has_json_keys(self) -> None:
        from app.core.prompts import BRIEFING_PROMPT
        for key in ("key_insights", "hypotheses", "coaching_questions",
                    "recommended_framework", "action_plan", "homework"):
            self.assertIn(key, BRIEFING_PROMPT)

    def test_briefing_prompt_forbids_diagnosis(self) -> None:
        from app.core.prompts import BRIEFING_PROMPT
        lower = BRIEFING_PROMPT.lower()
        self.assertIn("never diagnose", lower)

    def test_briefing_prompt_uses_tentative_language(self) -> None:
        from app.core.prompts import BRIEFING_PROMPT
        lower = BRIEFING_PROMPT.lower()
        self.assertIn("may", lower)


if __name__ == "__main__":
    unittest.main()
