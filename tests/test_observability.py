"""Tests for logging bootstrap and error file handler."""

import logging
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.observability import setup_logging


class StreamingCorrelationTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_generator_preserves_msg_id(self) -> None:
        # Bug 5 regression: the request coroutine resets its log context before
        # the streaming generator runs. The generator must re-bind the original
        # msg_id/user so LLM log lines emitted inside it stay correlated (not
        # msg=- user=-), and reset the context when it finishes.
        from app.api import openai_compat
        from app.api.chat import reset_runtime_state, session_manager
        from app.core.observability import _ContextFilter, _msg_id, reset_message

        reset_runtime_state()
        session_id = session_manager.get_or_create_session_id("alice")

        records: list[logging.LogRecord] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        handler = _Capture()
        handler.addFilter(_ContextFilter())
        root = logging.getLogger()
        previous_level = root.level
        root.setLevel(logging.INFO)
        root.addHandler(handler)
        try:
            reset_message()  # simulate the request context already cleared
            gen = openai_compat._stream_and_persist(
                history=[],
                system_prompt="",
                session_id=session_id,
                completion_id="chatcmpl-corr",
                created=0,
                direct_reply="Hello there.",
                msg_id="abc123",
                user_id="alice",
                t0=time.monotonic(),
            )
            async for _chunk in gen:
                pass
        finally:
            root.removeHandler(handler)
            handler.close()
            root.setLevel(previous_level)

        complete = [r for r in records if "stream_complete" in r.getMessage()]
        self.assertTrue(complete, "expected a stream_complete log line")
        self.assertTrue(all(r.msg_id == "abc123" for r in complete))
        self.assertTrue(all(r.user == "alice" for r in complete))
        # Context is reset once the generator finishes.
        self.assertEqual(_msg_id.get(), "-")


class ObservabilityLoggingTests(unittest.TestCase):
    def tearDown(self) -> None:
        root = logging.getLogger()
        for handler in list(root.handlers):
            root.removeHandler(handler)
            handler.close()

    def test_error_file_handler_writes_error_level_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            error_file = Path(tmp) / "errors.log"
            with patch("app.core.config.settings.log_error_file", str(error_file)):
                setup_logging(level="INFO")

                logger = logging.getLogger("test.observability")
                logger.info("should not appear in file")
                logger.error("something failed")

            contents = error_file.read_text(encoding="utf-8")
            self.assertIn("something failed", contents)
            self.assertNotIn("should not appear in file", contents)


if __name__ == "__main__":
    unittest.main()
