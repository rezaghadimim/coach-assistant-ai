"""CLI helper to export coaching sessions from SQLite as JSONL for fine-tuning."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.memory.store import MemoryStore
from app.memory.training_export import export_training_data


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export coaching sessions from SQLite to JSONL training data"
    )
    parser.add_argument(
        "--output",
        default="training_data.jsonl",
        help="Output JSONL file path (default: training_data.jsonl)",
    )
    parser.add_argument(
        "--db-path",
        default=settings.memory_db_path,
        help="SQLite database path (default: from settings)",
    )
    parser.add_argument(
        "--min-turns",
        type=int,
        default=4,
        help="Minimum user→assistant turn pairs per session (default: 4)",
    )
    parser.add_argument(
        "--include-open-sessions",
        action="store_true",
        help="Include sessions that have not been closed yet",
    )
    args = parser.parse_args()

    store = MemoryStore(args.db_path)
    stats = export_training_data(
        store,
        args.output,
        min_turns=args.min_turns,
        ended_only=not args.include_open_sessions,
    )
    print(
        f"Exported {stats.examples_written} session(s) "
        f"from {stats.sessions_scanned} scanned to '{args.output}'."
    )


if __name__ == "__main__":
    main()
