"""CI-safe guards for the LLM-router eval set and eval-script helpers.

These run offline (no Ollama).  They protect the *value* of the eval rather than
the model: a labeled set is only meaningful if its ``"none"`` rows are
data-shaped — i.e. they trip ``_is_data_request`` and therefore actually reach
the LLM router in production, where a wrong tool pick becomes a hallucinated
data answer.  The live accuracy measurement lives in
``tests/test_llm_router_integration.py`` (optional, skipped without Ollama).
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from app.core.llm import _is_data_request
from app.core.llm_router import _KNOWN_TOOLS

_EVAL_PATH = Path("data/eval/llm_router.jsonl")
_NONE = "none"


def _load_eval_script():
    """Import scripts/eval_llm_router.py by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location(
        "eval_llm_router", Path("scripts/eval_llm_router.py")
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class EvalDatasetIntegrityTests(unittest.TestCase):
    """The labeled set must stay well-formed and keep its trap coverage."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.eval_mod = _load_eval_script()
        cls.rows = cls.eval_mod._load_eval_set(str(_EVAL_PATH))

    def test_eval_file_exists_and_nonempty(self) -> None:
        self.assertTrue(_EVAL_PATH.exists(), f"missing eval set: {_EVAL_PATH}")
        self.assertGreaterEqual(len(self.rows), 20, "eval set is suspiciously small")

    def test_every_row_well_formed(self) -> None:
        valid_labels = _KNOWN_TOOLS | {_NONE}
        for i, row in enumerate(self.rows):
            self.assertIn("utterance", row, f"row {i} missing 'utterance'")
            self.assertIn("expected_tool", row, f"row {i} missing 'expected_tool'")
            self.assertIsInstance(row["utterance"], str)
            self.assertTrue(row["utterance"].strip(), f"row {i} has empty utterance")
            self.assertIn(
                row["expected_tool"], valid_labels,
                f"row {i} has unknown label {row['expected_tool']!r}",
            )

    def test_all_known_tools_are_covered(self) -> None:
        labels = {row["expected_tool"] for row in self.rows}
        missing = _KNOWN_TOOLS - labels
        self.assertFalse(missing, f"eval set never exercises these tools: {sorted(missing)}")

    def test_has_substantial_none_coverage(self) -> None:
        none_rows = [r for r in self.rows if r["expected_tool"] == _NONE]
        self.assertGreaterEqual(
            len(none_rows), 10,
            "the abstention guard needs a solid block of 'none' coaching rows",
        )

    def test_none_rows_are_mostly_data_shaped(self) -> None:
        """'none' rows must look like data requests, or the eval misses the trap.

        The router only fires for messages that pass ``_is_data_request``.  A
        coaching question that does NOT trip that gate never reaches the router,
        so it cannot test the hallucination path.  We require most 'none' rows to
        be data-shaped so the eval keeps exercising the realistic failure mode.
        """
        none_rows = [r["utterance"] for r in self.rows if r["expected_tool"] == _NONE]
        data_shaped = [u for u in none_rows if _is_data_request(u)]
        ratio = len(data_shaped) / len(none_rows) if none_rows else 0.0
        self.assertGreaterEqual(
            ratio, 0.7,
            f"only {len(data_shaped)}/{len(none_rows)} 'none' rows are data-shaped; "
            "add coaching questions that contain data-request trigger words",
        )


class EvalScriptHelperTests(unittest.TestCase):
    """Pure helpers in the eval script must behave (no Ollama needed)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.eval_mod = _load_eval_script()

    def test_f1_zero_when_no_signal(self) -> None:
        self.assertEqual(self.eval_mod._f1(0.0, 0.0), 0.0)

    def test_f1_harmonic_mean(self) -> None:
        self.assertAlmostEqual(self.eval_mod._f1(1.0, 1.0), 1.0)
        self.assertAlmostEqual(self.eval_mod._f1(0.5, 1.0), 2 / 3)

    def test_load_eval_set_round_trips(self) -> None:
        rows = self.eval_mod._load_eval_set(str(_EVAL_PATH))
        self.assertTrue(all("utterance" in r and "expected_tool" in r for r in rows))


if __name__ == "__main__":
    unittest.main()
