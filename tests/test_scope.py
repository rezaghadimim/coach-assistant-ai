"""Tests for the coaching-only scope guardrail."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.chat import store
from app.core.llm import _generate_with_tools
from app.core.scope import (
    OFF_TOPIC_REFUSAL,
    is_off_topic,
    is_openwebui_task,
    scope_guard,
)
from app.core.tools import TOOL_DEFINITIONS

_FOLLOW_UP_TASK = (
    "### Task:\n"
    "Suggest 3-5 relevant follow-up questions or prompts that the user might "
    "naturally ask next in this conversation as a **user**, based on the chat "
    "history, to help continue or deepen the discussion.\n"
    "### Output:\n"
    'JSON format: { "follow_ups": ["Question 1?", "Question 2?", "Question 3?"] }\n'
    "### Chat History:\n"
    "<chat_history>\n{{MESSAGES:END:6}}\n</chat_history>"
)

_TITLE_TASK = (
    "### Task:\nGenerate a concise, 3-5 word title.\n"
    "### Output:\nJSON format: { \"title\": \"your concise title here\" }"
)


class OffTopicDetectionTests(unittest.TestCase):
    def test_off_topic_examples(self) -> None:
        off_topic = [
            "Can you write some Python code to sort a list?",
            "Debug this code for me please",
            "What is 24 * 17?",
            "Calculate the integral of x squared",
            "What's the weather today in Tehran?",
            "Who won the game last night?",
            "What is the capital of France?",
            "Translate this sentence into Spanish",
            "Give me a recipe for chocolate cake",
            "What's the latest news on the stock price?",
        ]
        for message in off_topic:
            with self.subTest(message=message):
                self.assertTrue(is_off_topic(message))

    def test_coaching_messages_not_off_topic(self) -> None:
        coaching = [
            "I want to improve my focus this week.",
            "Help me set a SMART goal for my career change.",
            "Ali is feeling stressed about his relationship.",
            "How can I hold my client accountable for their habits?",
            "Save a note that Sara made progress on her goal.",
            "What are Ali's goals?",
            "I feel stuck and unmotivated lately.",
        ]
        for message in coaching:
            with self.subTest(message=message):
                self.assertFalse(is_off_topic(message))

    def test_empty_message_not_off_topic(self) -> None:
        self.assertFalse(is_off_topic("   "))


class OpenWebUITaskDetectionTests(unittest.TestCase):
    def test_detects_follow_up_task(self) -> None:
        self.assertTrue(is_openwebui_task(_FOLLOW_UP_TASK))

    def test_detects_title_task(self) -> None:
        self.assertTrue(is_openwebui_task(_TITLE_TASK))

    def test_detects_tags_task(self) -> None:
        self.assertTrue(is_openwebui_task('### Task:\nJSON format: { "tags": ["a"] }'))

    def test_normal_message_is_not_a_task(self) -> None:
        self.assertFalse(is_openwebui_task("I want to work on my confidence."))


class ScopeGuardTests(unittest.TestCase):
    def test_refuses_off_topic(self) -> None:
        self.assertEqual(scope_guard("Write Python code for me"), OFF_TOPIC_REFUSAL)

    def test_allows_coaching(self) -> None:
        self.assertIsNone(scope_guard("Help me plan my week as a coach."))

    def test_allows_openwebui_task_even_if_off_topic_keywords(self) -> None:
        self.assertIsNone(scope_guard(_FOLLOW_UP_TASK))


class GenerateWithToolsScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_off_topic_returns_refusal_without_llm_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            test_store = type(store)(str(Path(tmp) / "test.db"))
            mock_client = MagicMock()
            mock_client.post = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            with patch("app.core.llm_providers.ollama.httpx.AsyncClient", return_value=mock_client):
                reply = await _generate_with_tools(
                    [{"role": "user", "content": "Write Python code to sort a list"}],
                    "system",
                    TOOL_DEFINITIONS,
                    test_store,
                )

            self.assertEqual(reply, OFF_TOPIC_REFUSAL)
            mock_client.post.assert_not_called()

    async def test_openwebui_follow_up_task_returns_raw_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            test_store = type(store)(str(Path(tmp) / "test.db"))
            raw_json = '{"follow_ups": ["What is the smallest step you can take?"]}'

            async def fake_post(_url: str, *, json: dict) -> MagicMock:
                body = {"message": {"role": "assistant", "content": raw_json}}
                response = MagicMock()
                response.raise_for_status = MagicMock()
                response.json = MagicMock(return_value=body)
                return response

            mock_client = MagicMock()
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            with patch("app.core.llm_providers.ollama.httpx.AsyncClient", return_value=mock_client):
                reply = await _generate_with_tools(
                    [{"role": "user", "content": _FOLLOW_UP_TASK}],
                    "system",
                    TOOL_DEFINITIONS,
                    test_store,
                )

            self.assertEqual(reply, raw_json)

    async def test_malformed_tool_json_falls_back_to_plain_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            test_store = type(store)(str(Path(tmp) / "test.db"))
            malformed = (
                "Since your prompt doesn't specify a particular function call, "
                'I\'ll provide an empty response in the required JSON format.\n'
                '{"name": null, "parameters": {}}'
            )
            plain_reply = "Hello! How can I help with your coaching today?"
            call_count = 0

            async def fake_post(_url: str, *, json: dict) -> MagicMock:
                nonlocal call_count
                call_count += 1
                if json.get("tools"):
                    content = malformed
                else:
                    content = plain_reply
                body = {"message": {"role": "assistant", "content": content}}
                response = MagicMock()
                response.raise_for_status = MagicMock()
                response.json = MagicMock(return_value=body)
                return response

            mock_client = MagicMock()
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            with patch("app.core.llm_providers.ollama.httpx.AsyncClient", return_value=mock_client):
                reply = await _generate_with_tools(
                    [{"role": "user", "content": "Tell me about GROW"}],
                    "system",
                    TOOL_DEFINITIONS,
                    test_store,
                )

            self.assertEqual(reply, plain_reply)
            # main tool call (malformed) + plain fallback = 2 (LLM router skipped
            # because "Tell me about GROW" is not a data retrieval request)
            self.assertEqual(call_count, 2)


if __name__ == "__main__":
    unittest.main()
