"""Merge adapted Infinia data with exported real coaching sessions.

Usage:
    python scripts/merge_training_datasets.py
    python scripts/merge_training_datasets.py --infinia-weight 0.5
    python scripts/merge_training_datasets.py \\
        --infinia data/external/infinia/infinia_adapted.jsonl \\
        --sessions data/training/sessions.jsonl \\
        --output data/training/combined.jsonl

The output is a single JSONL file suitable for LoRA training.

Weighting:
    --infinia-weight 0.3 means 30% of the output rows come from Infinia.
    Rows from the smaller dataset are oversampled (with replacement) to reach
    the target proportion. If one source is missing or empty, the other is
    written as-is with a warning.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _tag_source(rows: list[dict], source: str) -> list[dict]:
    """Ensure metadata.source is set (non-destructive)."""
    result = []
    for row in rows:
        row = dict(row)
        row.setdefault("metadata", {})
        row["metadata"]["source"] = source
        result.append(row)
    return result


def merge(
    infinia_path: Path | None,
    sessions_path: Path | None,
    output_path: Path,
    infinia_weight: float = 0.3,
    seed: int = 42,
) -> dict:
    """Merge datasets and write combined.jsonl. Returns stats dict."""
    rng = random.Random(seed)

    infinia_rows: list[dict] = []
    sessions_rows: list[dict] = []

    if infinia_path and infinia_path.exists():
        infinia_rows = _tag_source(_read_jsonl(infinia_path), "infinia")
    elif infinia_path:
        print(f"WARNING: infinia file not found: {infinia_path}", file=sys.stderr)

    if sessions_path and sessions_path.exists():
        sessions_rows = _tag_source(_read_jsonl(sessions_path), "session")
    elif sessions_path:
        print(f"WARNING: sessions file not found: {sessions_path}", file=sys.stderr)

    if not infinia_rows and not sessions_rows:
        print("ERROR: Both input files are missing or empty.", file=sys.stderr)
        sys.exit(1)

    if not infinia_rows:
        print(
            "WARNING: No Infinia rows found — writing sessions only. "
            "Run prepare_infinia_training.py to generate adapted data.",
            file=sys.stderr,
        )
        combined = sessions_rows
    elif not sessions_rows:
        print(
            "WARNING: No session rows found — writing Infinia data only. "
            "This is the recommended path for a first fine-tune run.",
        )
        combined = infinia_rows
    else:
        total_sessions = len(sessions_rows)
        # Target: infinia_weight fraction from Infinia.
        # total_combined / sessions = 1 / (1 - infinia_weight)
        target_total = round(total_sessions / (1 - infinia_weight))
        target_infinia = target_total - total_sessions

        # Oversample infinia if needed (with replacement), subsample if too many.
        if target_infinia <= len(infinia_rows):
            sampled_infinia = rng.sample(infinia_rows, target_infinia)
        else:
            reps = (target_infinia // len(infinia_rows)) + 1
            pool = infinia_rows * reps
            sampled_infinia = rng.sample(pool, target_infinia)

        combined = sessions_rows + sampled_infinia
        rng.shuffle(combined)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        for row in combined:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    return {
        "total": len(combined),
        "infinia": len([r for r in combined if r.get("metadata", {}).get("source") == "infinia"]),
        "session": len([r for r in combined if r.get("metadata", {}).get("source") == "session"]),
        "output": str(output_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge adapted Infinia data with exported coaching sessions"
    )
    parser.add_argument(
        "--infinia",
        default="data/external/infinia/infinia_adapted.jsonl",
        help="Path to adapted Infinia JSONL (default: data/external/infinia/infinia_adapted.jsonl)",
    )
    parser.add_argument(
        "--sessions",
        default="data/training/sessions.jsonl",
        help="Path to exported sessions JSONL (default: data/training/sessions.jsonl)",
    )
    parser.add_argument(
        "--output",
        default="data/training/combined.jsonl",
        help="Output path (default: data/training/combined.jsonl)",
    )
    parser.add_argument(
        "--infinia-weight",
        type=float,
        default=0.3,
        help=(
            "Fraction of output rows from Infinia (0–1, default: 0.3). "
            "Ignored when only one source is available."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible sampling (default: 42)",
    )
    args = parser.parse_args()

    if not 0.0 < args.infinia_weight < 1.0:
        print("ERROR: --infinia-weight must be between 0 and 1 (exclusive).", file=sys.stderr)
        sys.exit(1)

    stats = merge(
        infinia_path=Path(args.infinia),
        sessions_path=Path(args.sessions),
        output_path=Path(args.output),
        infinia_weight=args.infinia_weight,
        seed=args.seed,
    )

    print(f"Merged dataset → {stats['output']}")
    print(f"  Total rows : {stats['total']}")
    print(f"  Infinia    : {stats['infinia']}")
    print(f"  Sessions   : {stats['session']}")
    print(
        "\nNext step:\n"
        "  python scripts/run_tuning_pipeline.py --profile mixed --steps train"
    )


if __name__ == "__main__":
    main()
