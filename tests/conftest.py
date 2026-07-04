"""Shared pytest setup for the suite.

Auth fails closed by default (no API key -> 401). Tests exercise business
logic without credentials, so run the suite in debug mode; tests that assert
auth behavior (tests/test_authz.py) override these flags explicitly.

Loaded before any test module imports `app.core.config`, so both the env var
and the direct settings mutation take effect regardless of import order.
"""

import os

os.environ.setdefault("DEBUG", "true")

from app.core.config import settings  # noqa: E402

settings.debug = True
