"""Tests for logging bootstrap and error file handler."""

import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.observability import setup_logging


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
