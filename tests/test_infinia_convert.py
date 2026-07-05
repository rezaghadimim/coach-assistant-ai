"""Tests for app/training/infinia_convert.py."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.training.infinia_convert import (
    adapt_completion_template,
    convert_dataset,
    row_to_record,
)

_SAMPLE_ROW = {
    "prompt": "I keep checking if I'm still here.",
    "completion": "The wind knows your name even when you forget it, and the earth holds your footsteps even when you can't feel them beneath you.",
    "topic": "self-doubt",
}


class TestAdaptCompletionTemplate(unittest.TestCase):
    def test_returns_string(self):
        result = adapt_completion_template(_SAMPLE_ROW["completion"], "self-doubt")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

    def test_appends_coaching_question(self):
        result = adapt_completion_template(_SAMPLE_ROW["completion"], "self-doubt")
        # Should end with a question mark.
        self.assertTrue(result.endswith("?"), f"Expected question: {result!r}")

    def test_unknown_topic_uses_generic_question(self):
        result = adapt_completion_template("Some response.", "unknown-topic")
        self.assertTrue(result.endswith("?"))

    def test_shorter_than_original_when_high_metaphor(self):
        long_metaphor = (
            "The wind carries your name while the sky holds the ocean of your breath "
            "as the flame of your spirit burns in the forest of your heart. "
            "And the river flows on."
        )
        result = adapt_completion_template(long_metaphor, "self-doubt")
        self.assertNotIn("river flows on", result)
        self.assertTrue(result.endswith("?"))
        first_sentence = "The wind carries your name while the sky holds the ocean of your breath "
        self.assertIn(first_sentence.rstrip(), result)

    def test_low_metaphor_keeps_full_completion(self):
        plain = "You are allowed to feel uncertain. That is human."
        result = adapt_completion_template(plain, "self-doubt")
        self.assertIn(plain, result)
        self.assertTrue(result.endswith("?"))


class TestRowToRecord(unittest.TestCase):
    def test_record_schema(self):
        record = row_to_record(_SAMPLE_ROW, "train", adapt_backend="template")
        self.assertIn("messages", record)
        self.assertIn("metadata", record)

        messages = record["messages"]
        roles = [m["role"] for m in messages]
        self.assertEqual(roles, ["system", "user", "assistant"])

        for msg in messages:
            self.assertIn("role", msg)
            self.assertIn("content", msg)
            self.assertTrue(msg["content"].strip())

    def test_metadata_fields(self):
        record = row_to_record(_SAMPLE_ROW, "holdout", adapt_backend="template")
        meta = record["metadata"]
        self.assertEqual(meta["split"], "holdout")
        self.assertEqual(meta["source"], "infinia")
        self.assertEqual(meta["topic"], "self-doubt")
        self.assertIn("original_completion", meta)

    def test_user_content_matches_prompt(self):
        record = row_to_record(_SAMPLE_ROW, "train", adapt_backend="template")
        user_msg = next(m for m in record["messages"] if m["role"] == "user")
        self.assertEqual(user_msg["content"], _SAMPLE_ROW["prompt"].strip())


class TestConvertDataset(unittest.TestCase):
    def _write_raw(self, tmp_dir: Path, rows: list[dict]) -> Path:
        raw_path = tmp_dir / "raw.jsonl"
        with raw_path.open("w") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")
        return raw_path

    def _make_rows(self, n: int) -> list[dict]:
        topics = ["self-doubt", "anxiety and overthinking", "burnout and exhaustion"]
        return [
            {
                "prompt": f"Prompt number {i}",
                "completion": f"The wind blows for you number {i}.",
                "topic": topics[i % len(topics)],
            }
            for i in range(n)
        ]

    def test_split_sizes_100_rows(self):
        rows = self._make_rows(100)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            raw_path = self._write_raw(tmp_dir, rows)
            stats = convert_dataset(raw_path, tmp_dir, seed=42, adapt_backend="template")

        self.assertEqual(stats.total, 100)
        self.assertEqual(stats.train + stats.val + stats.holdout, 100 - stats.skipped)
        # Train should be ~90%, holdout ~5%, val ~5%.
        self.assertGreater(stats.train, 80)
        self.assertGreater(stats.holdout, 0)
        self.assertGreater(stats.val, 0)

    def test_no_holdout_leakage_in_adapted(self):
        """Holdout rows must not appear in infinia_adapted.jsonl (train+val only)."""
        rows = self._make_rows(40)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            raw_path = self._write_raw(tmp_dir, rows)
            convert_dataset(raw_path, tmp_dir, seed=42, adapt_backend="template")

            adapted_path = tmp_dir / "infinia_adapted.jsonl"
            holdout_path = tmp_dir / "infinia_holdout.jsonl"

            adapted_rows = [
                json.loads(line)
                for line in adapted_path.read_text().splitlines()
                if line.strip()
            ]
            holdout_rows = [
                json.loads(line)
                for line in holdout_path.read_text().splitlines()
                if line.strip()
            ]

            adapted_splits = {r["metadata"]["split"] for r in adapted_rows}
            self.assertNotIn("holdout", adapted_splits)

            holdout_splits = {r["metadata"]["split"] for r in holdout_rows}
            self.assertEqual(holdout_splits, {"holdout"})

    def test_output_files_created(self):
        rows = self._make_rows(20)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            raw_path = self._write_raw(tmp_dir, rows)
            convert_dataset(raw_path, tmp_dir, seed=42, adapt_backend="template")

            for fname in (
                "infinia_train.jsonl",
                "infinia_val.jsonl",
                "infinia_holdout.jsonl",
                "infinia_adapted.jsonl",
                "infinia_raw_adapted.jsonl",
            ):
                self.assertTrue((tmp_dir / fname).exists(), f"Missing: {fname}")

    def test_sample_mode(self):
        rows = self._make_rows(100)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            raw_path = self._write_raw(tmp_dir, rows)
            stats = convert_dataset(
                raw_path, tmp_dir, seed=42, adapt_backend="template", sample=20
            )
        self.assertEqual(stats.total, 20)

    def test_valid_jsonl_schema(self):
        rows = self._make_rows(10)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            raw_path = self._write_raw(tmp_dir, rows)
            convert_dataset(raw_path, tmp_dir, seed=42, adapt_backend="template")

            for line in (tmp_dir / "infinia_train.jsonl").read_text().splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                self.assertIn("messages", record)
                roles = [m["role"] for m in record["messages"]]
                self.assertEqual(roles, ["system", "user", "assistant"])


if __name__ == "__main__":
    unittest.main()
