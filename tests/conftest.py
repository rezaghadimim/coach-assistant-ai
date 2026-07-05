"""Shared pytest setup for the suite.

Auth fails closed by default (no API key -> 401). Tests exercise business
logic without credentials, so run the suite in debug mode; tests that assert
auth behavior (tests/test_authz.py) override these flags explicitly.

Loaded before any test module imports `app.core.config`, so both the env var
and the direct settings mutation take effect regardless of import order.
"""

import atexit
import os
import shutil
import tempfile

os.environ.setdefault("DEBUG", "true")

# Point the shared MemoryStore singleton (app.api.chat.store, constructed at
# import time from settings.memory_db_path) at a throwaway file instead of the
# real data/coach_assistant.db. Must be set before app.core.config is first
# imported by any test module (this file loads first) so the whole suite gets
# an ephemeral database that starts empty every run and never pollutes — or is
# polluted by — real coach data on disk.
_TEST_DB_DIR = tempfile.mkdtemp(prefix="coach_assistant_tests_")
os.environ.setdefault("MEMORY_DB_PATH", os.path.join(_TEST_DB_DIR, "test.db"))
atexit.register(shutil.rmtree, _TEST_DB_DIR, True)

from app.core.config import settings  # noqa: E402

settings.debug = True
