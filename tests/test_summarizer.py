"""Tests for the LLM-based session summarizer with heuristic fallback."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class TestSummarizeSession(unittest.TestCase):

    def _run(self, coro):
        return asyncio.run(coro)

    def test_empty_messages_returns_heuristic(self) -> None:
        from app.memory.summarizer import summarize_session
        result = self._run(summarize_session([]))
        self.assertIn("Coaching Session Record", result)

    def test_llm_summary_returned_when_successful(self) -> None:
        from app.memory.summarizer import summarize_session

        fake_result = MagicMock()
        fake_result.content = "## Summary\n- Topics: career change\n- Action: update CV"

        with patch(
            "app.memory.summarizer.OllamaProvider",
        ) as MockProvider:
            instance = MockProvider.return_value
            instance.complete = AsyncMock(return_value=fake_result)
            messages = [
                {"role": "user", "content": "I want to change careers"},
                {"role": "assistant", "content": "What would success look like?"},
            ]
            result = self._run(summarize_session(messages))

        self.assertIn("Summary", result)
        self.assertIn("career", result)

    def test_heuristic_fallback_on_llm_error(self) -> None:
        from app.memory.summarizer import summarize_session

        with patch(
            "app.memory.summarizer.OllamaProvider",
        ) as MockProvider:
            instance = MockProvider.return_value
            instance.complete = AsyncMock(side_effect=ConnectionError("Ollama down"))
            messages = [
                {"role": "user", "content": "Feeling overwhelmed with work"},
                {"role": "assistant", "content": "Let's explore what's driving that."},
            ]
            result = self._run(summarize_session(messages))

        # Should fall back to heuristic — never raise
        self.assertIn("Coaching Session Record", result)
        self.assertIn("Feeling overwhelmed", result)

    def test_heuristic_fallback_on_empty_llm_response(self) -> None:
        from app.memory.summarizer import summarize_session

        fake_result = MagicMock()
        fake_result.content = "   "  # blank

        with patch(
            "app.memory.summarizer.OllamaProvider",
        ) as MockProvider:
            instance = MockProvider.return_value
            instance.complete = AsyncMock(return_value=fake_result)
            messages = [
                {"role": "user", "content": "I set a new goal"},
                {"role": "assistant", "content": "Great, let's make it SMART."},
            ]
            result = self._run(summarize_session(messages))

        self.assertIn("Coaching Session Record", result)

    def test_heuristic_summary_contains_topics(self) -> None:
        from app.memory.summarizer import _heuristic_summary
        messages = [
            {"role": "user", "content": "procrastination is a big issue for me"},
            {"role": "assistant", "content": "What is the smallest step you could take?"},
            {"role": "user", "content": "I think I need more structure"},
        ]
        result = _heuristic_summary(messages)
        self.assertIn("procrastination", result)
        self.assertIn("2", result)  # 2 exchanges


class TestSessionManagerAsync(unittest.TestCase):
    """Verify SessionManager's async summarizer integration."""

    def _run(self, coro):
        return asyncio.run(coro)

    def test_maybe_update_summary_below_threshold_is_noop(self) -> None:
        from app.memory.session import SessionManager
        from unittest.mock import MagicMock

        store = MagicMock()
        store.count_session_messages.return_value = 5
        sm = SessionManager(store)

        self._run(sm.maybe_update_summary("sess-1", threshold=20))
        store.update_session_summary.assert_not_called()

    def test_maybe_update_summary_above_threshold_calls_llm(self) -> None:
        from app.memory.session import SessionManager
        from unittest.mock import MagicMock

        store = MagicMock()
        store.count_session_messages.return_value = 25
        store.get_session_messages.return_value = [
            {"role": "user", "content": "career change"},
            {"role": "assistant", "content": "What does success look like?"},
        ]

        fake_result = MagicMock()
        fake_result.content = "## Summary\n- Topics: career"

        with patch(
            "app.memory.summarizer.OllamaProvider",
        ) as MockProvider:
            instance = MockProvider.return_value
            instance.complete = AsyncMock(return_value=fake_result)
            sm = SessionManager(store)
            self._run(sm.maybe_update_summary("sess-1", threshold=20))

        store.update_session_summary.assert_called_once()
        summary_arg = store.update_session_summary.call_args[0][1]
        self.assertIn("career", summary_arg)


if __name__ == "__main__":
    unittest.main()
