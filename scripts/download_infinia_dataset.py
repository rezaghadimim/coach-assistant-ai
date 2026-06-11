"""Download and cache the Infinia Life Coach dataset from Hugging Face.

Usage:
    python scripts/download_infinia_dataset.py
    python scripts/download_infinia_dataset.py --output-dir data/external/infinia
    python scripts/download_infinia_dataset.py --refresh   # force re-download

Writes:
    <output-dir>/raw.jsonl        — normalized rows: {prompt, completion, topic}
    <output-dir>/manifest.json    — row count, topic distribution, avg lengths, checksum
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

HF_DATASET_ID = "Infiniaai/infinia-life-coach-dataset"
DEFAULT_OUTPUT_DIR = Path("data/external/infinia")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_existing_manifest(output_dir: Path) -> dict | None:
    manifest_path = output_dir / "manifest.json"
    if manifest_path.exists():
        try:
            with manifest_path.open(encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _write_manifest(output_dir: Path, stats: dict) -> None:
    manifest_path = output_dir / "manifest.json"
    with manifest_path.open("w", encoding="utf-8") as fh:
        json.dump(stats, fh, indent=2, ensure_ascii=False)


def download(output_dir: Path, refresh: bool = False) -> dict:
    """Download the dataset and write raw.jsonl. Returns manifest stats."""
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / "raw.jsonl"

    if not refresh and raw_path.exists():
        manifest = _load_existing_manifest(output_dir)
        if manifest and manifest.get("checksum"):
            current_checksum = _sha256_file(raw_path)
            if current_checksum == manifest["checksum"]:
                print(f"Cache hit — using existing {raw_path} (pass --refresh to re-download)")
                return manifest

    print(f"Downloading {HF_DATASET_ID} from Hugging Face…")
    try:
        from datasets import load_dataset  # type: ignore[import]
    except ImportError:
        print(
            "ERROR: 'datasets' package not found.\n"
            "Install fine-tuning dependencies first:\n"
            "  pip install -r requirements-finetune.txt",
            file=sys.stderr,
        )
        sys.exit(1)

    ds = load_dataset(HF_DATASET_ID, split="train")

    rows = []
    topic_counter: Counter = Counter()
    prompt_lengths: list[int] = []
    completion_lengths: list[int] = []

    with raw_path.open("w", encoding="utf-8") as fh:
        for item in ds:
            row = {
                "prompt": item["prompt"],
                "completion": item["completion"],
                "topic": item.get("topic", ""),
            }
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            rows.append(row)
            topic_counter[row["topic"]] += 1
            prompt_lengths.append(len(row["prompt"]))
            completion_lengths.append(len(row["completion"]))

    total = len(rows)
    avg_prompt_len = sum(prompt_lengths) / total if total else 0
    avg_completion_len = sum(completion_lengths) / total if total else 0

    checksum = _sha256_file(raw_path)

    stats = {
        "dataset_id": HF_DATASET_ID,
        "total_rows": total,
        "avg_prompt_chars": round(avg_prompt_len, 1),
        "avg_completion_chars": round(avg_completion_len, 1),
        "topic_distribution": dict(sorted(topic_counter.items(), key=lambda x: -x[1])),
        "checksum": checksum,
        "raw_path": str(raw_path),
    }

    _write_manifest(output_dir, stats)
    print(f"Wrote {total} rows → {raw_path}")
    return stats


def _print_stats(stats: dict) -> None:
    print(f"\n--- Dataset stats: {stats['dataset_id']} ---")
    print(f"Total rows     : {stats['total_rows']}")
    print(f"Avg prompt len : {stats['avg_prompt_chars']} chars")
    print(f"Avg reply len  : {stats['avg_completion_chars']} chars")
    print("\nTopic distribution:")
    for topic, count in stats["topic_distribution"].items():
        bar = "#" * (count // 10)
        print(f"  {topic:<35} {count:>4}  {bar}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download and cache the Infinia Life Coach HF dataset"
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force re-download even if cache is valid",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    stats = download(output_dir, refresh=args.refresh)
    _print_stats(stats)


if __name__ == "__main__":
    main()
