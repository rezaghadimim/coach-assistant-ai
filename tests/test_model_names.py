"""Tests for app/training/model_names.py."""

import unittest

from app.training.model_names import ollama_model_name


class TestOllamaModelName(unittest.TestCase):
    def test_infinia_only(self):
        self.assertEqual(ollama_model_name("infinia-only"), "coach-assistant-infinia")

    def test_mixed(self):
        self.assertEqual(ollama_model_name("mixed"), "coach-assistant-mixed")

    def test_sequential(self):
        self.assertEqual(ollama_model_name("sequential"), "coach-assistant-sequential")

    def test_unknown_profile_raises(self):
        with self.assertRaises(ValueError):
            ollama_model_name("unknown")


if __name__ == "__main__":
    unittest.main()
