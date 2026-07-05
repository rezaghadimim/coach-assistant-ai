"""Unit tests for the remote TEI reranker client.

httpx is mocked so these tests run offline; no real TEI server is contacted.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.core.rerank_tei import rerank


class TestTeiRerank(unittest.TestCase):
    def test_empty_documents_short_circuits(self) -> None:
        with patch("app.core.rerank_tei.httpx.post") as mock_post:
            scores = rerank("query", [], base_url="http://tei:8080", timeout=30.0)
        self.assertEqual(scores, [])
        mock_post.assert_not_called()

    def test_scores_reordered_to_input_index(self) -> None:
        response = MagicMock()
        response.json.return_value = [
            {"index": 1, "score": 0.9},
            {"index": 0, "score": 0.2},
        ]
        with patch("app.core.rerank_tei.httpx.post", return_value=response) as mock_post:
            scores = rerank(
                "query", ["a", "b"], base_url="http://tei:8080/", timeout=30.0
            )
        self.assertEqual(scores, [0.2, 0.9])
        response.raise_for_status.assert_called_once()
        called_url = mock_post.call_args.args[0]
        self.assertEqual(called_url, "http://tei:8080/rerank")

    def test_raises_on_http_error(self) -> None:
        response = MagicMock()
        response.raise_for_status.side_effect = RuntimeError("500")
        with patch("app.core.rerank_tei.httpx.post", return_value=response):
            with self.assertRaises(RuntimeError):
                rerank("query", ["a"], base_url="http://tei:8080", timeout=30.0)


if __name__ == "__main__":
    unittest.main()
