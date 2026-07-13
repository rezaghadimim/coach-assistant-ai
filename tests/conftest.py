"""Shared pytest setup for the suite.

Auth fails closed by default (no API key -> 401). Tests exercise business
logic without credentials, so run the suite in debug mode; tests that assert
auth behavior (tests/test_authz.py) override these flags explicitly.

Loaded before any test module imports ``app.core.config``, so env pins and
the settings singleton stay deterministic regardless of developer ``.env``
or shell exports. See ``docs/TEST_EXECUTION.md``.
"""

import atexit
import os
import shutil
import tempfile

import pytest

from tests.isolation_support import (
    apply_env_overrides,
    apply_settings_overrides,
    install_network_guard,
    reset_rerank_probe_cache,
)

apply_env_overrides()
install_network_guard()

# Point the shared MemoryStore singleton (app.api.chat.store, constructed at
# import time from settings.memory_db_path) at a throwaway file instead of the
# real data/coach_assistant.db. Must be set before app.core.config is first
# imported by any test module (this file loads first) so the whole suite gets
# an ephemeral database that starts empty every run and never pollutes — or is
# polluted by — real coach data on disk.
_TEST_DB_DIR = tempfile.mkdtemp(prefix="coach_assistant_tests_")
os.environ["MEMORY_DB_PATH"] = os.path.join(_TEST_DB_DIR, "test.db")
atexit.register(shutil.rmtree, _TEST_DB_DIR, True)

from app.core.config import settings  # noqa: E402

apply_settings_overrides(settings)


@pytest.fixture(autouse=True)
def _isolated_rerank_probe_cache() -> None:
    """Prevent cross-test pollution of app.core.rerank._probe_ok (lifespan warm, probe tests)."""
    reset_rerank_probe_cache()
