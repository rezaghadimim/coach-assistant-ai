"""Evaluate tool routing accuracy against a labeled dataset.

Usage:
    python scripts/eval_tool_routing.py
    python scripts/eval_tool_routing.py --backend token
    python scripts/eval_tool_routing.py --backend embedding
    python scripts/eval_tool_routing.py --backend rerank
    python scripts/eval_tool_routing.py --hard
    python scripts/eval_tool_routing.py --eval-file data/eval/tool_routing.jsonl
    python scripts/eval_tool_routing.py --min-accuracy 0.90 --exit-nonzero

Outputs per-tool precision/recall/F1, overall accuracy, deferral rate,
and per-query latency (when --latency is passed).

The ``--hard`` flag switches the eval set to the held-out
``data/eval/tool_routing_hard.jsonl`` file which contains out-of-vocabulary
phrasings not present in ``routing.jsonl``.  This measures the generalization
capability of the embedding and rerank backends.

Exits with code 1 when accuracy falls below --min-accuracy (default 0.0, CI-safe).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate tool routing accuracy.")
    parser.add_argument(
        "--eval-file",
        default=None,
        help=(
            "Path to labeled JSONL eval set. "
            "Defaults to data/eval/tool_routing.jsonl, or the hard set when --hard is passed."
        ),
    )
    parser.add_argument(
        "--hard",
        action="store_true",
        help="Use the held-out hard eval set (data/eval/tool_routing_hard.jsonl).",
    )
    parser.add_argument(
        "--backend",
        choices=["token", "embedding", "auto", "rerank"],
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
    parser.add_argument(
        "--latency",
        action="store_true",
        help="Measure and report per-query classify latency (p50/p95).",
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


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = int(len(sorted_vals) * pct / 100)
    return sorted_vals[min(idx, len(sorted_vals) - 1)]


def main() -> int:
    args = _parse_args()

    # Apply overrides before importing settings-dependent modules.
    if args.backend:
        backend_env = args.backend
        # Map "rerank" to "auto" with rerank enabled so the flag is intuitive.
        if backend_env == "rerank":
            os.environ["TOOL_ROUTER_BACKEND"] = "auto"
            os.environ["TOOL_ROUTER_RERANK_ENABLED"] = "true"
        else:
            os.environ["TOOL_ROUTER_BACKEND"] = backend_env
            os.environ["TOOL_ROUTER_RERANK_ENABLED"] = "false"
    if args.threshold is not None:
        os.environ["TOOL_ROUTER_THRESHOLD"] = str(args.threshold)

    from app.core.tool_router import build_index, classify_tool, reset_index

    reset_index()
    count = build_index()
    print(f"Index built: {count} examples\n")

    # Determine eval file path.
    if args.eval_file:
        eval_path = Path(args.eval_file)
    elif args.hard:
        eval_path = Path("data/eval/tool_routing_hard.jsonl")
    else:
        eval_path = Path("data/eval/tool_routing.jsonl")

    if not eval_path.exists():
        print(f"ERROR: eval file not found: {eval_path}", file=sys.stderr)
        return 1

    rows = _load_eval_set(str(eval_path))
    if not rows:
        print("ERROR: eval file is empty.", file=sys.stderr)
        return 1

    label = "HARD" if args.hard else "STANDARD"
    print(f"Eval set: {eval_path} ({label}, {len(rows)} examples)\n")

    # Collect predictions
    tools = sorted({r["expected_tool"] for r in rows})
    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    fn: dict[str, int] = defaultdict(int)
    deferred = 0
    correct = 0
    errors: list[tuple[str, str, str]] = []
    latencies: list[float] = []

    for row in rows:
        utterance = row["utterance"]
        expected = row["expected_tool"]

        t0 = time.perf_counter()
        match = classify_tool(utterance, threshold=args.threshold)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        latencies.append(elapsed_ms)

        predicted = match.tool if match else "DEFERRED"
        backend_used = match.backend if match else "—"

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
            errors.append((utterance, expected, f"{predicted} [{backend_used}]"))

    total = len(rows)
    accuracy = correct / total if total > 0 else 0.0
    deferral_rate = deferred / total if total > 0 else 0.0

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
    print(f"Overall accuracy: {accuracy:.2%}  Deferral rate: {deferral_rate:.2%}")

    if args.latency and latencies:
        p50 = _percentile(latencies, 50)
        p95 = _percentile(latencies, 95)
        print(f"Latency — p50: {p50:.1f} ms  p95: {p95:.1f} ms")

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
