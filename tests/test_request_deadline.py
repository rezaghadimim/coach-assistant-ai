"""REL-06 — per-request overall deadline.

Each chat handler wraps its core work in ``asyncio.wait_for`` with
``settings.request_timeout_s``. A provider that never returns must yield a 504
at the budget rather than hanging for minutes.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.api.chat import reset_runtime_state
from app.core.config import settings
from main import app


async def _never_returns(*args, **kwargs) -> str:
    await asyncio.sleep(3600)
    return "unreachable"


class ChatDeadlineTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime_state()
        self.client = TestClient(app)
        self._orig = settings.request_timeout_s
        settings.request_timeout_s = 0.05

    def tearDown(self) -> None:
        settings.request_timeout_s = self._orig
        reset_runtime_state()

    def test_chat_returns_504_at_budget(self) -> None:
        # Force the LLM path (no direct reply) and stall the generator.
        with patch("app.api.chat.try_direct_reply_with_meta", return_value=None), patch(
            "app.api.chat.generate_response", new=AsyncMock(side_effect=_never_returns)
        ):
            response = self.client.post(
                "/api/chat",
                json={"user_id": "coach-deadline", "message": "help me coach"},
            )
        self.assertEqual(response.status_code, 504)

    def test_openai_compat_returns_504_at_budget(self) -> None:
        with patch(
            "app.api.openai_compat.try_direct_reply_with_meta", return_value=None
        ), patch(
            "app.api.openai_compat._generate_reply_or_unavailable",
            new=AsyncMock(side_effect=_never_returns),
        ):
            response = self.client.post(
                "/v1/chat/completions",
                json={
                    "model": "coach-assistant-ai",
                    "messages": [{"role": "user", "content": "help me coach"}],
                    "user": "coach-deadline-2",
                },
            )
        self.assertEqual(response.status_code, 504)


if __name__ == "__main__":
    unittest.main()
