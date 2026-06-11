"""Evaluate tool routing accuracy against a labeled dataset.

Usage:
    python scripts/eval_tool_routing.py
    python scripts/eval_tool_routing.py --backend token
    python scripts/eval_tool_routing.py --backend embedding
    python scripts/eval_tool_routing.py --eval-file data/eval/tool_routing.jsonl
    python scripts/eval_tool_routing.py --min-accuracy 0.90 --exit-nonzero

Outputs per-tool precision/recall/F1 and overall accuracy.
Exits with code 1 when accuracy falls below --min-accuracy (default 0.0, CI-safe).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate tool routing accuracy.")
    parser.add_argument(
        "--eval-file",
        default="data/eval/tool_routing.jsonl",
        help="Path to labeled JSONL eval set (default: data/eval/tool_routing.jsonl)",
    )
    parser.add_argument(
        "--backend",
        choices=["token", "embedding", "auto"],
        default=None,
        help="Override TOOL_ROUTER_BACKEND setting for this run.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Override TOOL_ROUTER_THRESHOLD for this run.",
    )
    parser.add_argument(
        "--min-accuracy",
        type=float,
        default=0.0,
        help="Exit non-zero if overall accuracy falls below this value.",
    )
    parser.add_argument(
        "--exit-nonzero",
        action="store_true",
        help="Exit with code 1 when accuracy < --min-accuracy.",
    )
    parser.add_argument(
        "--show-errors",
        action="store_true",
        help="Print mispredicted utterances.",
    )
    return parser.parse_args()


def _load_eval_set(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0.0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def main() -> int:
    args = _parse_args()

    # Apply overrides before importing settings-dependent modules.
    if args.backend:
        os.environ["TOOL_ROUTER_BACKEND"] = args.backend
    if args.threshold is not None:
        os.environ["TOOL_ROUTER_THRESHOLD"] = str(args.threshold)

    from app.core.tool_router import build_index, classify_tool, reset_index

    reset_index()
    count = build_index()
    print(f"Index built: {count} examples\n")

    eval_path = Path(args.eval_file)
    if not eval_path.exists():
        print(f"ERROR: eval file not found: {eval_path}", file=sys.stderr)
        return 1

    rows = _load_eval_set(str(eval_path))
    if not rows:
        print("ERROR: eval file is empty.", file=sys.stderr)
        return 1

    # Collect predictions
    tools = sorted({r["expected_tool"] for r in rows})
    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    fn: dict[str, int] = defaultdict(int)
    deferred = 0
    correct = 0
    errors: list[tuple[str, str, str]] = []

    for row in rows:
        utterance = row["utterance"]
        expected = row["expected_tool"]
        match = classify_tool(utterance, threshold=args.threshold)
        predicted = match.tool if match else "DEFERRED"

        if predicted == "DEFERRED":
            deferred += 1
            fn[expected] += 1
            errors.append((utterance, expected, predicted))
            continue

        if predicted == expected:
            correct += 1
            tp[expected] += 1
        else:
            fp[predicted] += 1
            fn[expected] += 1
            errors.append((utterance, expected, predicted))

    total = len(rows)
    accuracy = correct / total if total > 0 else 0.0

    # Per-tool metrics
    print(f"{'Tool':<22} {'TP':>4} {'FP':>4} {'FN':>4} {'Prec':>6} {'Rec':>6} {'F1':>6}")
    print("-" * 60)
    for tool in tools:
        t = tp[tool]
        f_pos = fp[tool]
        f_neg = fn[tool]
        prec = t / (t + f_pos) if (t + f_pos) > 0 else 0.0
        rec = t / (t + f_neg) if (t + f_neg) > 0 else 0.0
        f1 = _f1(prec, rec)
        print(f"{tool:<22} {t:>4} {f_pos:>4} {f_neg:>4} {prec:>6.2f} {rec:>6.2f} {f1:>6.2f}")

    print("-" * 60)
    print(f"\nTotal: {total}  Correct: {correct}  Deferred: {deferred}")
    print(f"Overall accuracy: {accuracy:.2%}")

    if args.show_errors and errors:
        print(f"\nMispredictions ({len(errors)}):")
        for utterance, expected, predicted in errors:
            print(f"  [{expected}] → [{predicted}]  \"{utterance}\"")

    if args.exit_nonzero and accuracy < args.min_accuracy:
        print(
            f"\nFAIL: accuracy {accuracy:.2%} < required {args.min_accuracy:.2%}",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
