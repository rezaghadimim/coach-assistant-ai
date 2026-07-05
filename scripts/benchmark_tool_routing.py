"""Benchmark tool routing across all available backends.

Compares token / embedding / rerank (and optionally LLM) on the standard eval
set and the hard held-out set.  Reports accuracy, stage-1 recall (for
embedding/rerank), deferral rate, and p50/p95 latency per backend.

Backends whose dependencies are unavailable are automatically skipped:
  - ``embedding`` and ``rerank`` require Ollama with the embed model.
  - ``rerank`` additionally requires ``fastembed`` to be installed.
  - ``llm`` requires Ollama with the chat model.

Usage:
    python scripts/benchmark_tool_routing.py
    python scripts/benchmark_tool_routing.py --backends token embedding rerank
    python scripts/benchmark_tool_routing.py --no-hard
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark tool routing across backends on standard and hard eval sets."
    )
    parser.add_argument(
        "--backends",
        nargs="+",
        choices=["token", "embedding", "rerank"],
        default=["token", "embedding", "rerank"],
        help="Backends to benchmark (default: all three).",
    )
    parser.add_argument(
        "--no-hard",
        action="store_true",
        help="Skip the hard held-out eval set.",
    )
    parser.add_argument(
        "--standard-file",
        default="data/eval/tool_routing.jsonl",
        help="Path to the standard eval set.",
    )
    parser.add_argument(
        "--hard-file",
        default="data/eval/tool_routing_hard.jsonl",
        help="Path to the hard held-out eval set.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_eval_set(path: str) -> list[dict]:
    rows: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = int(len(sorted_vals) * pct / 100)
    return sorted_vals[min(idx, len(sorted_vals) - 1)]


def _probe_embed() -> bool:
    try:
        from app.core.embeddings import probe_embed_model
        return probe_embed_model()
    except Exception:
        return False


def _probe_rerank() -> bool:
    try:
        from app.core.rerank import probe_rerank_model
        return probe_rerank_model()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Single-backend eval
# ---------------------------------------------------------------------------


def _run_eval(
    rows: list[dict],
    *,
    classify_fn,
    label: str,
) -> dict:
    correct = 0
    deferred = 0
    latencies: list[float] = []

    for row in rows:
        utterance = row["utterance"]
        expected = row["expected_tool"]

        t0 = time.perf_counter()
        match = classify_fn(utterance)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        latencies.append(elapsed_ms)

        predicted = match.tool if match else "DEFERRED"

        if predicted == "DEFERRED":
            deferred += 1
        elif predicted == expected:
            correct += 1

    total = len(rows)
    return {
        "label": label,
        "total": total,
        "correct": correct,
        "deferred": deferred,
        "accuracy": correct / total if total else 0.0,
        "deferral_rate": deferred / total if total else 0.0,
        "p50_ms": _percentile(latencies, 50),
        "p95_ms": _percentile(latencies, 95),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _print_results(results: list[dict], set_name: str) -> None:
    print(f"\n{'=' * 72}")
    print(f"  {set_name}")
    print(f"{'=' * 72}")
    header = f"{'Backend':<12} {'Total':>6} {'Correct':>8} {'Deferred':>9} {'Accuracy':>9} {'Deferral':>9} {'p50ms':>7} {'p95ms':>7}"
    print(header)
    print("-" * 72)
    for r in results:
        print(
            f"{r['label']:<12} {r['total']:>6} {r['correct']:>8} {r['deferred']:>9} "
            f"{r['accuracy']:>8.1%} {r['deferral_rate']:>8.1%} "
            f"{r['p50_ms']:>6.1f} {r['p95_ms']:>6.1f}"
        )


def main() -> int:
    args = _parse_args()

    # Load eval files
    standard_path = Path(args.standard_file)
    hard_path = Path(args.hard_file)

    if not standard_path.exists():
        print(f"ERROR: standard eval file not found: {standard_path}", file=sys.stderr)
        return 1

    standard_rows = _load_eval_set(str(standard_path))
    hard_rows: list[dict] = []
    if not args.no_hard:
        if hard_path.exists():
            hard_rows = _load_eval_set(str(hard_path))
        else:
            print(f"WARNING: hard eval file not found: {hard_path} — skipping", file=sys.stderr)

    # Probe backend availability
    print("Probing backends...")
    embed_ok = False
    rerank_ok = False

    requested = set(args.backends)

    if "embedding" in requested or "rerank" in requested:
        embed_ok = _probe_embed()
        print(f"  Embedding (Ollama): {'OK' if embed_ok else 'UNAVAILABLE'}")

    if "rerank" in requested and embed_ok:
        rerank_ok = _probe_rerank()
        print(f"  Rerank (fastembed): {'OK' if rerank_ok else 'UNAVAILABLE'}")

    backends_to_run: list[tuple[str, str, dict]] = []
    # (backend_name, display_label, env_overrides)

    if "token" in requested:
        backends_to_run.append(("token", "token", {"TOOL_ROUTER_BACKEND": "token", "TOOL_ROUTER_RERANK_ENABLED": "false"}))

    if "embedding" in requested:
        if embed_ok:
            backends_to_run.append(("embedding", "embedding", {"TOOL_ROUTER_BACKEND": "auto", "TOOL_ROUTER_RERANK_ENABLED": "false"}))
        else:
            print("  Skipping 'embedding' backend — Ollama embed model unavailable.")

    if "rerank" in requested:
        if rerank_ok and embed_ok:
            backends_to_run.append(("rerank", "rerank", {"TOOL_ROUTER_BACKEND": "auto", "TOOL_ROUTER_RERANK_ENABLED": "true"}))
        else:
            missing = []
            if not embed_ok:
                missing.append("Ollama embed model")
            if not rerank_ok:
                missing.append("fastembed cross-encoder")
            print(f"  Skipping 'rerank' backend — {', '.join(missing)} unavailable.")

    if not backends_to_run:
        print("\nNo backends available to benchmark.", file=sys.stderr)
        return 1

    print(f"\nRunning {len(backends_to_run)} backend(s) on {len(standard_rows)} standard examples"
          + (f" + {len(hard_rows)} hard examples" if hard_rows else "") + "...\n")

    standard_results: list[dict] = []
    hard_results: list[dict] = []

    from app.core.tool_router import classify_tool, reset_index, build_index

    for _backend_name, label, env_overrides in backends_to_run:
        # Apply env overrides
        for k, v in env_overrides.items():
            os.environ[k] = v

        reset_index()
        build_index()

        def _classify(msg: str, _label: str = label) -> object:
            return classify_tool(msg)

        print(f"  [{label}] standard set ...", end=" ", flush=True)
        r_std = _run_eval(standard_rows, classify_fn=_classify, label=label)
        standard_results.append(r_std)
        print(f"accuracy={r_std['accuracy']:.1%}")

        if hard_rows:
            print(f"  [{label}] hard set    ...", end=" ", flush=True)
            r_hard = _run_eval(hard_rows, classify_fn=_classify, label=label)
            hard_results.append(r_hard)
            print(f"accuracy={r_hard['accuracy']:.1%}")

    _print_results(standard_results, f"STANDARD eval set  ({standard_path})")
    if hard_results:
        _print_results(hard_results, f"HARD eval set      ({hard_path})")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
