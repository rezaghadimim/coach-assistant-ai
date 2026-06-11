"""Prepare Infinia dataset for LoRA fine-tuning.

Reads the cached raw.jsonl produced by download_infinia_dataset.py,
adapts completions to coach voice, and writes split JSONL files.

Usage:
    python scripts/prepare_infinia_training.py
    python scripts/prepare_infinia_training.py --adapt-backend ollama
    python scripts/prepare_infinia_training.py --sample 50   # quick review run
    python scripts/prepare_infinia_training.py --adapt-backend ollama --ollama-model llama3.1:8b

Outputs (all in --data-dir):
    infinia_train.jsonl     — 90% of rows, adapted
    infinia_val.jsonl       — 5%  of rows, adapted (for training early stopping)
    infinia_holdout.jsonl   — 5%  of rows, adapted (eval only — never train on these)
    infinia_adapted.jsonl   — train + val combined (input to merge script)
    infinia_raw_adapted.jsonl — all rows including holdout (audit trail)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.training.infinia_convert import convert_dataset


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Adapt and split the cached Infinia dataset for LoRA training"
    )
    parser.add_argument(
        "--data-dir",
        default="data/external/infinia",
        help="Directory containing raw.jsonl (default: data/external/infinia)",
    )
    parser.add_argument(
        "--adapt-backend",
        choices=["template", "ollama"],
        default="template",
        help=(
            "Adaptation backend: 'template' is fast and deterministic; "
            "'ollama' rewrites via local LLM for better quality (default: template)"
        ),
    )
    parser.add_argument(
        "--ollama-base-url",
        default="http://localhost:11434",
        help="Ollama base URL (default: http://localhost:11434)",
    )
    parser.add_argument(
        "--ollama-model",
        default="llama3.1:8b",
        help="Ollama model to use for adaptation (default: llama3.1:8b)",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=None,
        help="Only process N rows (useful for a quick manual review before full run)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible splits (default: 42)",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    raw_path = data_dir / "raw.jsonl"

    if not raw_path.exists():
        print(
            f"ERROR: {raw_path} not found.\n"
            "Run download_infinia_dataset.py first:\n"
            "  python scripts/download_infinia_dataset.py",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.adapt_backend == "ollama":
        print(
            f"Using Ollama adaptation ({args.ollama_model} @ {args.ollama_base_url})\n"
            "This rewrites each completion via the local LLM — expect ~5-10 min for the full dataset."
        )
    else:
        print("Using template adaptation (fast, deterministic).")

    if args.sample:
        print(f"Sample mode: processing {args.sample} rows only.")

    stats = convert_dataset(
        raw_path=raw_path,
        output_dir=data_dir,
        adapt_backend=args.adapt_backend,
        ollama_base_url=args.ollama_base_url,
        ollama_model=args.ollama_model,
        sample=args.sample,
        seed=args.seed,
    )

    print(f"\nConversion complete:")
    print(f"  Total rows    : {stats.total}")
    print(f"  Train         : {stats.train}  → {data_dir}/infinia_train.jsonl")
    print(f"  Val           : {stats.val}   → {data_dir}/infinia_val.jsonl")
    print(f"  Holdout       : {stats.holdout}  → {data_dir}/infinia_holdout.jsonl")
    print(f"  Skipped       : {stats.skipped}")
    print(f"\nCombined train+val → {data_dir}/infinia_adapted.jsonl")
    print("\nNext step:")
    if args.sample:
        print(
            "  Review the sample output manually, then re-run without --sample for the full dataset:\n"
            "  python scripts/prepare_infinia_training.py --adapt-backend ollama"
        )
    else:
        print(
            "  To train Infinia-only:\n"
            "    python scripts/run_tuning_pipeline.py --profile infinia-only --steps train\n"
            "  To build a mixed dataset first:\n"
            "    python scripts/merge_training_datasets.py"
        )


if __name__ == "__main__":
    main()
