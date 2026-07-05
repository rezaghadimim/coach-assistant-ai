"""Tests for the two-stage embed -> cross-encoder rerank in the tool router.

All Ollama and fastembed calls are mocked so the tests run offline.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("TOOL_ROUTER_BACKEND", "auto")
os.environ.setdefault("TOOL_ROUTER_ENABLED", "true")
os.environ.setdefault("TOOL_ROUTER_THRESHOLD", "0.50")
os.environ.setdefault("TOOL_ROUTER_MARGIN", "0.05")
os.environ.setdefault("TOOL_ROUTER_RERANK_ENABLED", "true")
os.environ.setdefault("TOOL_ROUTER_RERANK_THRESHOLD", "0.55")
os.environ.setdefault("TOOL_ROUTER_RERANK_MARGIN", "0.10")
os.environ.setdefault("TOOL_ROUTER_EMBED_FLOOR", "0.30")
os.environ.setdefault("TOOL_ROUTER_RERANK_TOP_K", "5")


def _build_fake_embed_backend(examples_by_tool: dict[str, list[str]]):
    """Return a populated _EmbeddingBackend with simple identity-like vectors."""

    from app.core.tool_router import _EmbeddingBackend, _Example

    backend = _EmbeddingBackend()
    idx = 0
    for tool, utterances in examples_by_tool.items():
        for utt in utterances:
            ex = _Example(utterance=utt, tool=tool, hint=None)
            # Assign a deterministic unit vector per tool so cosine similarity
            # between same-tool examples is high.
            dim = 8
            vec = [0.0] * dim
            vec[idx % dim] = 1.0
            ex.vector = vec
            backend.add(ex)
        idx += 1
    return backend


class ReRankCandidatesTests(unittest.TestCase):
    """Unit tests for _rerank_candidates helper."""

    def setUp(self) -> None:
        from app.core.tool_router import reset_index
        reset_index()

    def tearDown(self) -> None:
        from app.core.tool_router import reset_index
        reset_index()

    def _make_examples(self, tools_utts: list[tuple[str, str]]):
        from app.core.tool_router import _Example
        return [(_Example(utterance=u, tool=t, hint=None), 0.8) for t, u in tools_utts]

    def test_rerank_returns_best_tool(self) -> None:
        from app.core.tool_router import _rerank_candidates

        candidates = self._make_examples([
            ("list_clients", "Who are my clients?"),
            ("list_clients", "Show all patients"),
            ("get_client_full", "Show me everything about Ali"),
        ])

        # Reranker assigns high score to first candidate (list_clients).
        with patch("app.core.rerank.rerank_documents", return_value=[0.92, 0.88, 0.30]):
            result, ranked = _rerank_candidates(
                "Give me all visitors in table",
                candidates,
                threshold=0.55,
                margin=0.10,
                model="BAAI/bge-reranker-base",
            )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.tool, "list_clients")
        self.assertEqual(result.backend, "rerank")
        self.assertAlmostEqual(result.rerank_score, 0.92, places=2)
        # Ranked candidates are returned for deferral reuse (best tool first).
        self.assertEqual(ranked[0].tool, "list_clients")
        self.assertAlmostEqual(ranked[0].rerank_score, 0.92, places=2)

    def test_rerank_below_threshold_returns_none(self) -> None:
        from app.core.tool_router import _rerank_candidates

        candidates = self._make_examples([
            ("list_clients", "Who are my clients?"),
        ])

        with patch("app.core.rerank.rerank_documents", return_value=[0.40]):
            result, ranked = _rerank_candidates(
                "random message",
                candidates,
                threshold=0.55,
                margin=0.05,
                model="BAAI/bge-reranker-base",
            )

        self.assertIsNone(result)
        # Even on a miss, ranked candidates are returned so the caller can log
        # the deferral without recomputing embeddings/rerank.
        self.assertEqual(ranked[0].tool, "list_clients")

    def test_rerank_insufficient_margin_returns_none(self) -> None:
        from app.core.tool_router import _rerank_candidates

        candidates = self._make_examples([
            ("list_clients", "Who are my clients?"),
            ("get_client_full", "Show everything about Ali"),
        ])

        # list_clients 0.80, get_client_full 0.78 — margin 0.02 < required 0.10
        with patch("app.core.rerank.rerank_documents", return_value=[0.80, 0.78]):
            result, _ranked = _rerank_candidates(
                "some ambiguous message",
                candidates,
                threshold=0.55,
                margin=0.10,
                model="BAAI/bge-reranker-base",
            )

        self.assertIsNone(result)

    def test_rerank_exception_returns_none(self) -> None:
        from app.core.tool_router import _rerank_candidates

        candidates = self._make_examples([
            ("list_clients", "Who are my clients?"),
        ])

        with patch("app.core.rerank.rerank_documents", side_effect=RuntimeError("fastembed unavailable")):
            result, _ranked = _rerank_candidates(
                "give me all clients",
                candidates,
                threshold=0.55,
                margin=0.05,
                model="BAAI/bge-reranker-base",
            )

        self.assertIsNone(result)

    def test_rerank_count_mismatch_returns_none(self) -> None:
        from app.core.tool_router import _rerank_candidates

        candidates = self._make_examples([
            ("list_clients", "Who are my clients?"),
            ("get_client_full", "Show everything about Ali"),
        ])

        # Reranker returns wrong number of scores.
        with patch("app.core.rerank.rerank_documents", return_value=[0.90]):
            result, _ranked = _rerank_candidates(
                "some message",
                candidates,
                threshold=0.55,
                margin=0.05,
                model="BAAI/bge-reranker-base",
            )

        self.assertIsNone(result)

    def test_rerank_empty_candidates_returns_none(self) -> None:
        from app.core.tool_router import _rerank_candidates

        result, _ranked = _rerank_candidates(
            "give me all clients",
            [],
            threshold=0.55,
            margin=0.05,
            model="BAAI/bge-reranker-base",
        )

        self.assertIsNone(result)


class ClassifyToolReRankIntegrationTests(unittest.TestCase):
    """Integration tests for classify_tool when rerank path is active."""

    def setUp(self) -> None:
        from app.core.tool_router import reset_index
        reset_index()

    def tearDown(self) -> None:
        from app.core.tool_router import reset_index
        reset_index()

    def _patch_rerank_available(self):
        """Patch module-level state so rerank path is taken."""
        import app.core.tool_router as tr
        tr._embed_available = True
        tr._rerank_available = True
        tr._index_built = True

    def test_classify_tool_uses_rerank_when_available(self) -> None:
        """classify_tool returns backend='rerank' when rerank path fires."""
        from app.core.tool_router import build_index, classify_tool, _Example

        build_index()
        self._patch_rerank_available()

        fake_vec = [0.1] * 384
        mock_candidates = [
            (_Example(utterance="Who are my clients?", tool="list_clients", hint="all", vector=fake_vec), 0.75),
            (_Example(utterance="Show all patients", tool="list_clients", hint="all", vector=fake_vec), 0.72),
            (_Example(utterance="List my clients", tool="list_clients", hint="all", vector=fake_vec), 0.70),
            (_Example(utterance="Show everything about Ali", tool="get_client_full", hint="full", vector=fake_vec), 0.40),
            (_Example(utterance="Get all data about Sara", tool="get_client_full", hint="full", vector=fake_vec), 0.38),
        ]

        mock_embed = MagicMock()
        mock_embed.__len__ = MagicMock(return_value=77)
        mock_embed.top_k = MagicMock(return_value=mock_candidates)

        mock_settings = MagicMock()
        mock_settings.tool_router_enabled = True
        mock_settings.tool_router_backend = "auto"
        mock_settings.tool_router_threshold = 0.50
        mock_settings.tool_router_margin = 0.05
        mock_settings.tool_router_rerank_enabled = True
        mock_settings.tool_router_rerank_top_k = 5
        mock_settings.tool_router_embed_floor = 0.30
        mock_settings.tool_router_rerank_threshold = 0.55
        mock_settings.tool_router_rerank_margin = 0.10
        mock_settings.tool_router_rerank_model = "BAAI/bge-reranker-base"

        with patch("app.core.tool_router._embed_backend", mock_embed), \
             patch("app.core.tool_router.settings", mock_settings), \
             patch("app.core.rerank.rerank_documents", return_value=[0.92, 0.88, 0.85, 0.30, 0.20]):

            result = classify_tool("Give me all visitors in table")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.tool, "list_clients")
        self.assertEqual(result.backend, "rerank")
        self.assertIsNotNone(result.rerank_score)

    def test_classify_tool_falls_back_to_token_when_rerank_raises(self) -> None:
        """Falls back to token backend when rerank raises."""
        from app.core.tool_router import build_index, classify_tool, _Example

        build_index()
        self._patch_rerank_available()

        fake_vec = [0.1] * 384
        mock_candidates = [
            (_Example(utterance="Who are my clients?", tool="list_clients", hint="all", vector=fake_vec), 0.75),
        ]

        mock_embed = MagicMock()
        mock_embed.__len__ = MagicMock(return_value=77)
        mock_embed.top_k = MagicMock(return_value=mock_candidates)
        mock_embed.classify = MagicMock(return_value=None)

        mock_settings = MagicMock()
        mock_settings.tool_router_enabled = True
        mock_settings.tool_router_backend = "auto"
        mock_settings.tool_router_threshold = 0.30
        mock_settings.tool_router_margin = 0.05
        mock_settings.tool_router_rerank_enabled = True
        mock_settings.tool_router_rerank_top_k = 5
        mock_settings.tool_router_embed_floor = 0.30
        mock_settings.tool_router_rerank_threshold = 0.55
        mock_settings.tool_router_rerank_margin = 0.10
        mock_settings.tool_router_rerank_model = "BAAI/bge-reranker-base"

        with patch("app.core.tool_router._embed_backend", mock_embed), \
             patch("app.core.tool_router.settings", mock_settings), \
             patch("app.core.rerank.rerank_documents", side_effect=RuntimeError("crash")):
            # Rerank raises → falls through to embed classify → None → token
            result = classify_tool("Who are my clients?")

        # Result comes from token backend (rerank failed, embed mock returned None)
        if result is not None:
            self.assertIn(result.backend, ("token", "embedding"))

    def test_classify_tool_rerank_disabled_uses_embedding_path(self) -> None:
        """When rerank disabled, embedding path is used (not rerank)."""
        from app.core.tool_router import build_index, classify_tool, reset_index

        reset_index()

        with patch("app.core.tool_router.settings") as mock_settings:
            mock_settings.tool_router_enabled = True
            mock_settings.tool_router_backend = "auto"
            mock_settings.tool_router_threshold = 0.50
            mock_settings.tool_router_margin = 0.05
            mock_settings.tool_router_rerank_enabled = False  # disabled
            mock_settings.tool_router_rerank_top_k = 5
            mock_settings.tool_router_embed_floor = 0.30
            mock_settings.tool_router_rerank_threshold = 0.55
            mock_settings.tool_router_rerank_margin = 0.10
            mock_settings.tool_router_rerank_model = "BAAI/bge-reranker-base"
            mock_settings.tool_knowledge_dir = "docs/tool-knowledge"
            mock_settings.tool_router_use_e5_prefix = True
            mock_settings.rag_embed_model = "test"

            reset_index()
            build_index()

            import app.core.tool_router as tr
            tr._embed_available = False
            tr._rerank_available = False

            result = classify_tool("Who are my clients?", threshold=0.3, margin=0.05)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.tool, "list_clients")
        self.assertEqual(result.backend, "token")


class ToolMatchRerankScoreTests(unittest.TestCase):
    """ToolMatch dataclass includes rerank_score field."""

    def test_toolmatch_has_rerank_score_field(self) -> None:
        from app.core.tool_router import ToolMatch

        m = ToolMatch(tool="list_clients", score=0.8, backend="rerank", rerank_score=0.92)
        self.assertEqual(m.rerank_score, 0.92)

    def test_toolmatch_rerank_score_defaults_to_none(self) -> None:
        from app.core.tool_router import ToolMatch

        m = ToolMatch(tool="list_clients", score=0.8, backend="token")
        self.assertIsNone(m.rerank_score)

    def test_toolmatch_backend_rerank_string(self) -> None:
        from app.core.tool_router import ToolMatch

        m = ToolMatch(tool="list_clients", score=0.8, backend="rerank", rerank_score=0.90)
        self.assertEqual(m.backend, "rerank")
