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

    def test_summary_runs_once_per_boundary_not_every_message(self) -> None:
        """REL-01: messages 20..25 with threshold 20 summarize exactly once."""
        from app.memory.session import SessionManager

        store = MagicMock()
        store.get_session_messages.return_value = [
            {"role": "user", "content": "career change"},
        ]
        sm = SessionManager(store)

        async def scenario() -> None:
            with patch(
                "app.memory.session.summarize_session",
                new=AsyncMock(return_value="## Summary"),
            ) as mocked:
                for count in range(20, 26):
                    store.count_session_messages.return_value = count
                    await sm.maybe_update_summary("sess-1", threshold=20)
                self.assertEqual(mocked.await_count, 1)
                # Crossing the next boundary (40) re-summarizes exactly once more.
                for count in range(40, 43):
                    store.count_session_messages.return_value = count
                    await sm.maybe_update_summary("sess-1", threshold=20)
                self.assertEqual(mocked.await_count, 2)

        self._run(scenario())
        self.assertEqual(store.update_session_summary.call_count, 2)

    def test_failed_summary_releases_boundary_claim(self) -> None:
        from app.memory.session import SessionManager

        store = MagicMock()
        store.count_session_messages.return_value = 21
        store.get_session_messages.return_value = [{"role": "user", "content": "x"}]
        sm = SessionManager(store)

        async def scenario() -> None:
            with patch(
                "app.memory.session.summarize_session",
                new=AsyncMock(side_effect=[RuntimeError("boom"), "## Summary"]),
            ) as mocked:
                with self.assertRaises(RuntimeError):
                    await sm.maybe_update_summary("sess-1", threshold=20)
                await sm.maybe_update_summary("sess-1", threshold=20)
                self.assertEqual(mocked.await_count, 2)

        self._run(scenario())
        store.update_session_summary.assert_called_once()

    def test_schedule_update_summary_does_not_block_request(self) -> None:
        """REL-01: the endpoint path returns before the summarizer LLM call finishes."""
        from app.memory.session import SessionManager

        store = MagicMock()
        store.count_session_messages.return_value = 20
        store.get_session_messages.return_value = [{"role": "user", "content": "x"}]
        sm = SessionManager(store)

        async def scenario() -> None:
            release = asyncio.Event()

            async def slow_summary(_messages):
                await release.wait()
                return "## Summary"

            with patch("app.memory.session.summarize_session", new=slow_summary):
                sm.schedule_update_summary("sess-1", threshold=20)
                # Returned immediately: the summary has not been written yet.
                store.update_session_summary.assert_not_called()
                release.set()
                await asyncio.gather(*sm._summary_tasks)

        self._run(scenario())
        store.update_session_summary.assert_called_once()

    def test_schedule_below_threshold_spawns_no_task(self) -> None:
        from app.memory.session import SessionManager

        store = MagicMock()
        store.count_session_messages.return_value = 3
        sm = SessionManager(store)

        async def scenario() -> None:
            sm.schedule_update_summary("sess-1", threshold=20)
            self.assertEqual(len(sm._summary_tasks), 0)

        self._run(scenario())


if __name__ == "__main__":
    unittest.main()
