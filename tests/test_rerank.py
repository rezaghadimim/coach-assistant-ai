"""Unit tests for the local fastembed cross-encoder reranker client.

The ONNX model is never loaded here: ``_get_encoder`` is patched with a fake
encoder so these tests run fast and fully offline in CI. End-to-end behaviour
against the real model lives in ``tests/test_rerank_integration.py``.
"""

from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.core.rerank as rerank_mod
from app.core.rerank import (
    _has_incomplete_blobs,
    _onnx_model_ready,
    _purge_rerank_model_cache,
    probe_rerank_model,
    rerank_documents,
)


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    exp_x = math.exp(x)
    return exp_x / (1.0 + exp_x)


class _FakeEncoder:
    """Stand-in for fastembed ``TextCrossEncoder``."""

    def __init__(self, scores):
        self._scores = scores
        self.last_batch_size: int | None = None
        self.last_documents: list[str] | None = None

    def rerank(self, query: str, documents, batch_size: int = 64):
        self.last_batch_size = batch_size
        self.last_documents = list(documents)
        if callable(self._scores):
            return self._scores(query, self.last_documents)
        return list(self._scores)


class _ResettableReranker(unittest.TestCase):
    def setUp(self) -> None:
        self._reset_state()

    def tearDown(self) -> None:
        self._reset_state()

    @staticmethod
    def _reset_state() -> None:
        rerank_mod._encoder = None
        rerank_mod._encoder_model_name = None
        rerank_mod._probe_ok = None


class TestRerankDocuments(_ResettableReranker):
    def test_returns_scores_aligned_with_input_order(self) -> None:
        logits = [0.1, 0.9, 0.4]
        fake = _FakeEncoder(logits)
        with patch.object(rerank_mod, "_get_encoder", return_value=fake):
            scores = rerank_documents("query", ["a", "b", "c"])
        self.assertEqual(scores, [_sigmoid(v) for v in logits])

    def test_empty_documents_short_circuits(self) -> None:
        with patch.object(rerank_mod, "_get_encoder") as mock_get:
            scores = rerank_documents("query", [])
        self.assertEqual(scores, [])
        mock_get.assert_not_called()

    def test_truncates_passages_to_max_chars(self) -> None:
        long_doc = "x" * 5000
        fake = _FakeEncoder([1.0])
        with patch.object(rerank_mod, "_get_encoder", return_value=fake):
            rerank_documents("query", [long_doc], max_passage_chars=100)
        assert fake.last_documents is not None
        self.assertEqual(len(fake.last_documents[0]), 100)

    def test_passes_batch_size_to_encoder(self) -> None:
        fake = _FakeEncoder([0.1, 0.2])
        with patch.object(rerank_mod, "_get_encoder", return_value=fake):
            rerank_documents("query", ["a", "b"], batch_size=8)
        self.assertEqual(fake.last_batch_size, 8)

    def test_raises_on_score_count_mismatch(self) -> None:
        fake = _FakeEncoder([0.5])  # one score for two documents
        with patch.object(rerank_mod, "_get_encoder", return_value=fake):
            with self.assertRaises(ValueError):
                rerank_documents("query", ["a", "b"])

    def test_success_marks_probe_cached(self) -> None:
        fake = _FakeEncoder([0.3, 0.7])
        with patch.object(rerank_mod, "_get_encoder", return_value=fake):
            rerank_documents("query", ["a", "b"])
        self.assertIs(rerank_mod.rerank_probe_cached(), True)


class TestProbeRerankModel(_ResettableReranker):
    def test_probe_true_when_model_scores(self) -> None:
        fake = _FakeEncoder([1.0])
        with patch.object(rerank_mod, "fastembed_installed", return_value=True):
            with patch.object(rerank_mod, "_get_encoder", return_value=fake):
                self.assertTrue(probe_rerank_model())

    def test_probe_false_when_fastembed_missing(self) -> None:
        with patch.object(rerank_mod, "fastembed_installed", return_value=False):
            self.assertFalse(probe_rerank_model())
        self.assertIs(rerank_mod.rerank_probe_cached(), False)

    def test_probe_is_cached_and_does_not_reload(self) -> None:
        fake = _FakeEncoder([1.0])
        with patch.object(rerank_mod, "fastembed_installed", return_value=True):
            with patch.object(rerank_mod, "_get_encoder", return_value=fake) as mock_get:
                self.assertTrue(probe_rerank_model())
                # Second call must short-circuit on the cached True result.
                self.assertTrue(probe_rerank_model())
                self.assertEqual(mock_get.call_count, 1)

    def test_probe_false_when_scoring_raises(self) -> None:
        with patch.object(rerank_mod, "fastembed_installed", return_value=True):
            with patch.object(rerank_mod, "_get_encoder", side_effect=RuntimeError("boom")):
                self.assertFalse(probe_rerank_model())


class TestRerankCacheHygiene(unittest.TestCase):
    model_name = "BAAI/bge-reranker-base"

    def test_onnx_model_ready_when_cache_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(_onnx_model_ready(tmp, self.model_name))

    def test_onnx_model_not_ready_without_onnx_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = (
                Path(tmp)
                / "models--BAAI--bge-reranker-base"
                / "snapshots"
                / "abc123"
            )
            (snapshot / "onnx").mkdir(parents=True)
            self.assertFalse(_onnx_model_ready(tmp, self.model_name))

    def test_detects_incomplete_blobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            blobs = Path(tmp) / "models--BAAI--bge-reranker-base" / "blobs"
            blobs.mkdir(parents=True)
            (blobs / "deadbeef.incomplete").write_text("partial")
            self.assertTrue(_has_incomplete_blobs(tmp, self.model_name))

    def test_purge_removes_partial_cache_and_locks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hf_dir = Path(tmp) / "models--BAAI--bge-reranker-base"
            hf_dir.mkdir()
            lock_dir = Path(tmp) / ".locks" / hf_dir.name
            lock_dir.mkdir(parents=True)

            _purge_rerank_model_cache(tmp, self.model_name)

            self.assertFalse(hf_dir.exists())
            self.assertFalse(lock_dir.exists())

    def test_onnx_ready_returns_true_when_complete_model_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            onnx_file = (
                Path(tmp)
                / "models--BAAI--bge-reranker-base"
                / "snapshots"
                / "rev1"
                / "onnx"
                / "model.onnx"
            )
            onnx_file.parent.mkdir(parents=True)
            onnx_file.write_bytes(b"\x00" * 16)  # non-empty ONNX file
            self.assertTrue(_onnx_model_ready(tmp, self.model_name))


class TestProbeCachedNonBlocking(_ResettableReranker):
    """Verify that rerank_probe_cached() never triggers a model load."""

    def test_returns_none_before_any_probe(self) -> None:
        self.assertIsNone(rerank_mod.rerank_probe_cached())

    def test_returns_true_after_successful_probe(self) -> None:
        fake = _FakeEncoder([1.0])
        with patch.object(rerank_mod, "fastembed_installed", return_value=True):
            with patch.object(rerank_mod, "_get_encoder", return_value=fake):
                probe_rerank_model()
        self.assertIs(rerank_mod.rerank_probe_cached(), True)

    def test_returns_false_after_failed_probe(self) -> None:
        with patch.object(rerank_mod, "fastembed_installed", return_value=False):
            probe_rerank_model()
        self.assertIs(rerank_mod.rerank_probe_cached(), False)

    def test_cached_does_not_call_get_encoder(self) -> None:
        """rerank_probe_cached() must never load the encoder."""
        with patch.object(rerank_mod, "_get_encoder") as mock_get:
            rerank_mod.rerank_probe_cached()
        mock_get.assert_not_called()


class TestConfigCachePath(unittest.TestCase):
    """Verify rag_rerank_cache_dir is always resolved to an absolute path."""

    def test_default_cache_dir_is_absolute(self) -> None:
        from app.core.config import settings

        self.assertTrue(
            Path(settings.rag_rerank_cache_dir).is_absolute(),
            f"Expected absolute path, got: {settings.rag_rerank_cache_dir}",
        )

    def test_relative_env_override_is_resolved_to_absolute(self) -> None:
        from pydantic_settings import BaseSettings

        import app.core.config as config_mod

        original = config_mod.settings
        try:
            # Simulate an env override with a relative path.
            new_settings = config_mod.Settings(
                rag_rerank_cache_dir="relative/rerank_cache"
            )
            self.assertTrue(
                Path(new_settings.rag_rerank_cache_dir).is_absolute(),
                f"Relative override not resolved: {new_settings.rag_rerank_cache_dir}",
            )
            self.assertIn("rerank_cache", new_settings.rag_rerank_cache_dir)
        finally:
            config_mod.settings = original

    def test_absolute_env_override_is_unchanged(self) -> None:
        import app.core.config as config_mod

        original = config_mod.settings
        try:
            new_settings = config_mod.Settings(
                rag_rerank_cache_dir="/custom/absolute/rerank_cache"
            )
            self.assertEqual(
                new_settings.rag_rerank_cache_dir,
                "/custom/absolute/rerank_cache",
            )
        finally:
            config_mod.settings = original


if __name__ == "__main__":
    unittest.main()
