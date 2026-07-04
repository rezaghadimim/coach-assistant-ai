"""SEC-04 — source_id must not permit path traversal.

`source_id` is used as an on-disk directory segment when registering a source
(`app/api/collections.py`). It is constrained to a slug pattern so traversal
sequences (`..`, `/`, absolute paths) are rejected at the schema boundary,
before any filesystem write happens.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from pydantic import ValidationError

from app.models.schemas import SourceCreateRequest


class SourceIdValidationTests(unittest.TestCase):
    def test_traversal_source_id_rejected(self) -> None:
        for bad in ("../../etc", "..", "a/b", "/etc/passwd", "foo/../bar", "UPPER"):
            with self.assertRaises(ValidationError, msg=f"accepted {bad!r}"):
                SourceCreateRequest(title="t", source_type="transcript", source_id=bad)

    def test_valid_slug_accepted(self) -> None:
        req = SourceCreateRequest(
            title="t", source_type="transcript", source_id="grow-intro-01"
        )
        self.assertEqual(req.source_id, "grow-intro-01")

    def test_source_id_optional(self) -> None:
        req = SourceCreateRequest(title="t", source_type="transcript")
        self.assertIsNone(req.source_id)


class SourceCreateEndpointTraversalTests(unittest.TestCase):
    """The endpoint rejects a traversal source_id (422) before any mkdir."""

    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from main import app

        self.client = TestClient(app)

    def test_post_traversal_source_id_returns_422_and_creates_nothing(self) -> None:
        from app.core.config import settings

        collections_root = Path(settings.rag_collections_dir)
        escaped = collections_root.parent / "etc"
        before = escaped.exists()

        response = self.client.post(
            "/api/collections/any-collection/sources",
            json={
                "title": "t",
                "source_type": "transcript",
                "source_id": "../../etc",
            },
        )

        self.assertEqual(response.status_code, 422)
        # The request body is rejected before the handler runs, so nothing is
        # created outside the collections directory.
        self.assertEqual(escaped.exists(), before)


if __name__ == "__main__":
    unittest.main()
