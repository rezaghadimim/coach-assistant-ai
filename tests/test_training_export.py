"""Tests for fine-tuning training data export."""

import json
import tempfile
import unittest
from pathlib import Path

from app.core.prompts import COACH_ASSISTANT_SYSTEM_PROMPT
from app.memory.store import MemoryStore
from app.memory.training_export import (
    count_coaching_turns,
    export_training_data,
    session_to_training_record,
)


class TrainingExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "export.db"
        self.store = MemoryStore(str(self.db_path))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _seed_session(
        self,
        user_id: str,
        messages: list[tuple[str, str]],
        *,
        ended: bool = True,
    ) -> str:
        self.store.upsert_user(user_id)
        session_id = self.store.create_session(user_id)
        for role, content in messages:
            self.store.add_message(session_id, role, content)
        if ended:
            self.store.end_session(session_id, summary="Session summary")
        return session_id

    def test_count_coaching_turns(self) -> None:
        messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
            {"role": "user", "content": "I'm stuck"},
            {"role": "assistant", "content": "Tell me more"},
        ]
        self.assertEqual(count_coaching_turns(messages), 2)

    def test_session_to_training_record_skips_short_sessions(self) -> None:
        messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ]
        record = session_to_training_record(messages, min_turns=2)
        self.assertIsNone(record)

    def test_export_training_data_writes_jsonl(self) -> None:
        self._seed_session(
            "coach-1",
            [
                ("user", "I feel stuck in my career"),
                ("assistant", "What does stuck look like day to day?"),
                ("user", "I avoid applying for roles"),
                ("assistant", "What gets in the way when you think about applying?"),
                ("user", "Fear of rejection"),
                ("assistant", "What would one small step look like this week?"),
                ("user", "Update my resume"),
                ("assistant", "Great. When will you block time for that?"),
            ],
        )
        self._seed_session(
            "coach-2",
            [
                ("user", "Quick question"),
                ("assistant", "Sure"),
            ],
        )

        output_path = Path(self.temp_dir.name) / "training.jsonl"
        stats = export_training_data(self.store, output_path, min_turns=4)

        self.assertEqual(stats.sessions_scanned, 2)
        self.assertEqual(stats.examples_written, 1)

        lines = output_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        record = json.loads(lines[0])
        self.assertEqual(record["messages"][0]["role"], "system")
        self.assertEqual(record["messages"][0]["content"], COACH_ASSISTANT_SYSTEM_PROMPT)
        self.assertEqual(record["messages"][-1]["role"], "assistant")

    def test_export_training_data_can_include_open_sessions(self) -> None:
        self._seed_session(
            "coach-open",
            [
                ("user", "One"),
                ("assistant", "Two"),
                ("user", "Three"),
                ("assistant", "Four"),
                ("user", "Five"),
                ("assistant", "Six"),
                ("user", "Seven"),
                ("assistant", "Eight"),
            ],
            ended=False,
        )

        output_path = Path(self.temp_dir.name) / "open.jsonl"
        stats = export_training_data(
            self.store,
            output_path,
            min_turns=4,
            ended_only=False,
        )
        self.assertEqual(stats.examples_written, 1)


if __name__ == "__main__":
    unittest.main()
