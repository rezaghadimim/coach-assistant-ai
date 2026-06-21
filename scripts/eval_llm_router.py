"""Evaluate the LLM-router fallback (app/core/llm_router.py) against a labeled set.

The LLM router is the one place in the fast path where the small model makes an
open-ended decision: given a data-shaped message, pick ONE tool — or abstain
with "none".  Its dangerous failure mode is **hallucination**: returning a real
tool for a general coaching question, which makes the system fetch and present
client data the coach never asked for.

This script measures that directly.  Unlike ``eval_tool_routing.py`` (which only
has data-request rows), the eval set here includes ``"none"`` rows — coaching
questions, many of them deliberately *data-shaped* (they trip ``_is_data_request``
so they actually reach the router in production).  The headline metric is the
**hallucination rate**: how often a coaching question gets assigned a tool.

Usage:
    PYTHONPATH=. python scripts/eval_llm_router.py
    PYTHONPATH=. python scripts/eval_llm_router.py --show-errors
    PYTHONPATH=. python scripts/eval_llm_router.py --limit 20
    PYTHONPATH=. python scripts/eval_llm_router.py --min-accuracy 0.90 \
        --max-hallucination-rate 0.10 --exit-nonzero

Requires a reachable Ollama running ``settings.ollama_model`` (default
``llama3.1:8b``).  When Ollama is unreachable it prints a SKIP notice and exits 0
(so it never breaks CI), unless ``--exit-nonzero`` is passed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

_DEFAULT_EVAL = "data/eval/llm_router.jsonl"
_NONE = "none"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate LLM-router classification + abstention.")
    parser.add_argument("--eval-file", default=_DEFAULT_EVAL, help="Path to labeled JSONL eval set.")
    parser.add_argument("--limit", type=int, default=None, help="Evaluate only the first N rows.")
    parser.add_argument("--concurrency", type=int, default=4, help="Concurrent router calls (default 4).")
    parser.add_argument("--show-errors", action="store_true", help="Print mispredicted utterances.")
    parser.add_argument(
        "--min-accuracy", type=float, default=0.0,
        help="Required overall accuracy for --exit-nonzero (default 0.0).",
    )
    parser.add_argument(
        "--max-hallucination-rate", type=float, default=1.0,
        help="Max allowed hallucination rate (tool assigned to a 'none' row) for --exit-nonzero.",
    )
    parser.add_argument(
        "--exit-nonzero", action="store_true",
        help="Exit 1 when accuracy < --min-accuracy or hallucination rate > --max-hallucination-rate.",
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


def _ollama_reachable() -> bool:
    import httpx

    from app.core.config import settings

    try:
        resp = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=3.0)
        return resp.status_code == 200
    except Exception:
        return False


async def _classify(utterance: str, provider, sem: asyncio.Semaphore) -> str:
    """Return the predicted tool name, or "none" when the router abstains."""
    from app.core.llm_router import classify_tool_llm

    async with sem:
        match = await classify_tool_llm(utterance, provider=provider)
    return match.tool if match is not None else _NONE


def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0.0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


async def _run(args: argparse.Namespace) -> int:
    from app.core.config import settings
    from app.core.llm import _is_data_request
    from app.core.llm_providers.ollama import OllamaProvider

    eval_path = Path(args.eval_file)
    if not eval_path.exists():
        print(f"ERROR: eval file not found: {eval_path}", file=sys.stderr)
        return 1

    rows = _load_eval_set(str(eval_path))
    if args.limit is not None:
        rows = rows[: args.limit]
    if not rows:
        print("ERROR: eval file is empty.", file=sys.stderr)
        return 1

    if not _ollama_reachable():
        print(
            f"SKIP: Ollama unreachable at {settings.ollama_base_url} — "
            f"this eval needs a live model ({settings.ollama_model}).",
            file=sys.stderr,
        )
        return 1 if args.exit_nonzero else 0

    print(f"Eval set: {eval_path} ({len(rows)} rows)")
    print(f"Router model: {settings.ollama_model}  (llm_fallback_enabled="
          f"{settings.tool_router_llm_fallback_enabled})\n")

    provider = OllamaProvider()
    sem = asyncio.Semaphore(max(1, args.concurrency))

    t0 = time.perf_counter()
    predictions = await asyncio.gather(
        *(_classify(row["utterance"], provider, sem) for row in rows)
    )
    elapsed = time.perf_counter() - t0

    # Per-tool confusion (treating "none" as a label like any other).
    labels = sorted({row["expected_tool"] for row in rows} | {_NONE})
    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    fn: dict[str, int] = defaultdict(int)

    correct = 0
    # Hallucination tracking: "none" rows that were assigned a tool.
    none_total = 0
    none_data_shaped = 0          # passes _is_data_request → actually reaches the router in prod
    hallucinated = 0              # any "none" row given a tool
    hallucinated_data_shaped = 0  # the realistic, high-value subset
    # Missed data requests: real tool rows the router abstained on.
    data_total = 0
    over_abstained = 0
    errors: list[tuple[str, str, str]] = []

    for row, predicted in zip(rows, predictions):
        utterance = row["utterance"]
        expected = row["expected_tool"]
        is_none = expected == _NONE
        data_shaped = _is_data_request(utterance)

        if is_none:
            none_total += 1
            none_data_shaped += int(data_shaped)
        else:
            data_total += 1

        if predicted == expected:
            correct += 1
            tp[expected] += 1
        else:
            fp[predicted] += 1
            fn[expected] += 1
            errors.append((utterance, expected, predicted))
            if is_none:  # coaching question wrongly assigned a tool
                hallucinated += 1
                hallucinated_data_shaped += int(data_shaped)
            elif predicted == _NONE:  # real data request the router dropped
                over_abstained += 1

    total = len(rows)
    accuracy = correct / total if total else 0.0
    halluc_rate = hallucinated / none_total if none_total else 0.0
    halluc_rate_ds = (
        hallucinated_data_shaped / none_data_shaped if none_data_shaped else 0.0
    )
    miss_rate = over_abstained / data_total if data_total else 0.0

    # Per-label precision/recall/F1.
    print(f"{'Label':<22} {'TP':>4} {'FP':>4} {'FN':>4} {'Prec':>6} {'Rec':>6} {'F1':>6}")
    print("-" * 60)
    for label in labels:
        t, f_pos, f_neg = tp[label], fp[label], fn[label]
        prec = t / (t + f_pos) if (t + f_pos) else 0.0
        rec = t / (t + f_neg) if (t + f_neg) else 0.0
        print(f"{label:<22} {t:>4} {f_pos:>4} {f_neg:>4} {prec:>6.2f} {rec:>6.2f} {_f1(prec, rec):>6.2f}")
    print("-" * 60)

    print(f"\nTotal: {total}  Correct: {correct}  Overall accuracy: {accuracy:.2%}")
    print(f"Latency: {elapsed:.1f}s total, {elapsed / total * 1000:.0f} ms/row avg "
          f"(concurrency={args.concurrency})")

    print("\n── Hallucination guard (the point of this eval) ──")
    print(f"Coaching ('none') rows:            {none_total}  "
          f"(of which data-shaped: {none_data_shaped})")
    print(f"Hallucinated (tool assigned):      {hallucinated}  → rate {halluc_rate:.2%}")
    print(f"  ...on data-shaped rows (realistic): {hallucinated_data_shaped} "
          f"→ rate {halluc_rate_ds:.2%}")
    print(f"Data requests dropped to 'none':   {over_abstained}/{data_total} "
          f"→ miss rate {miss_rate:.2%}")

    if args.show_errors and errors:
        print(f"\nMispredictions ({len(errors)}):")
        for utterance, expected, predicted in errors:
            tag = " [HALLUCINATION]" if expected == _NONE else ""
            print(f"  [{expected}] → [{predicted}]{tag}  \"{utterance}\"")

    if args.exit_nonzero:
        failed = False
        if accuracy < args.min_accuracy:
            print(f"\nFAIL: accuracy {accuracy:.2%} < required {args.min_accuracy:.2%}",
                  file=sys.stderr)
            failed = True
        if halluc_rate > args.max_hallucination_rate:
            print(f"FAIL: hallucination rate {halluc_rate:.2%} > "
                  f"allowed {args.max_hallucination_rate:.2%}", file=sys.stderr)
            failed = True
        if failed:
            return 1

    return 0


def main() -> int:
    args = _parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
