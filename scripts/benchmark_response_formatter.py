"""Benchmark the LLM response formatter: deterministic template vs LLM formatting pass.

Compares two modes across a built-in eval set of coach data-retrieval messages:

  OFF — deterministic template only (fast path returns ``_format_direct_lookup_reply``)
  ON  — deterministic template + LLM formatting call

Metrics measured per sample:
  latency_off_ms   Time to produce the deterministic reply (µs-range, measured in process)
  latency_on_ms    Time to produce the LLM-formatted reply (Ollama round-trip)
  pii_preserved    Boolean: all expected PII tokens appear verbatim in the formatted reply
  char_delta       Formatted length minus deterministic length (negative = shorter = better)

Usage:
    python scripts/benchmark_response_formatter.py
    python scripts/benchmark_response_formatter.py --samples 8
    python scripts/benchmark_response_formatter.py --model llama3.1:8b
    python scripts/benchmark_response_formatter.py --no-llm   # deterministic only
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Allow running from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ---------------------------------------------------------------------------
# Built-in eval set
# Each entry has:
#   user_message   — the coach's original question
#   tool_result    — the raw string returned by execute_tool()
#   expected_pii   — PII tokens that must appear verbatim in the formatted reply
# ---------------------------------------------------------------------------

_EVAL_SET = [
    {
        "user_message": "What is Ali's email?",
        "tool_result": (
            "Client ID: ali\n"
            "Name: Ali Hassan\n"
            "Email: ali.hassan@example.com\n"
            "Phone: (not set)\n"
            "Age: 32\n"
            "Occupation: Software Engineer\n"
            "Background: (not set)"
        ),
        "expected_pii": ["ali.hassan@example.com"],
    },
    {
        "user_message": "Show me Sara's phone number",
        "tool_result": (
            "Client ID: sara\n"
            "Name: Sara Karimi\n"
            "Email: (not set)\n"
            "Phone: +98-912-000-1234\n"
            "Age: 28\n"
            "Occupation: Marketing Manager\n"
            "Background: (not set)"
        ),
        "expected_pii": ["+98-912-000-1234"],
    },
    {
        "user_message": "Give me all clients",
        "tool_result": (
            "Registered clients:\n"
            "- Ali Hassan (ID: ali)\n"
            "- Sara Karimi (ID: sara)\n"
            "- Reza Ahmadi (ID: reza)\n"
            "- Leila Sadeghi (ID: leila)"
        ),
        "expected_pii": [],
    },
    {
        "user_message": "Tell me everything about Reza",
        "tool_result": (
            "## Profile\n"
            "Client ID: reza\n"
            "Name: Reza Ahmadi\n"
            "Email: reza@coachapp.io\n"
            "Phone: 09121234567\n"
            "Age: 40\n"
            "Occupation: Entrepreneur\n"
            "Background: Executive coaching client since 2024\n\n"
            "## Notes\n"
            "[GOAL] Career transition (2026-01-10): Wants to move into venture capital within 18 months.\n"
            "[DECISION] Left corporate job (2026-02-05): Resigned to focus on his startup full-time."
        ),
        "expected_pii": ["reza@coachapp.io", "09121234567"],
    },
    {
        "user_message": "What is Leila's age?",
        "tool_result": (
            "Client ID: leila\n"
            "Name: Leila Sadeghi\n"
            "Email: leila.s@example.org\n"
            "Phone: (not set)\n"
            "Age: 35\n"
            "Occupation: Teacher\n"
            "Background: (not set)"
        ),
        "expected_pii": [],  # age-only question — email must not be required in output
    },
    {
        "user_message": "Show Sara's goals",
        "tool_result": (
            "[GOAL] ID 12 (2026-03-01): Complete a leadership certification by end of Q3.\n"
            "[GOAL] ID 15 (2026-04-15): Start her own consulting practice within 12 months."
        ),
        "expected_pii": [],
    },
    {
        "user_message": "Who are my clients?",
        "tool_result": (
            "Registered clients:\n"
            "- Ali Hassan (ID: ali)\n"
            "- Sara Karimi (ID: sara)"
        ),
        "expected_pii": [],
    },
    {
        "user_message": "Get Ali's full profile",
        "tool_result": (
            "## Profile\n"
            "Client ID: ali\n"
            "Name: Ali Hassan\n"
            "Email: ali.hassan@example.com\n"
            "Phone: (not set)\n"
            "Age: 32\n"
            "Occupation: Software Engineer\n"
            "Background: Referred by corporate wellness programme\n\n"
            "## Notes\n"
            "[PROGRESS] ID 3 (2026-05-20): Completed time-management module.\n"
            "[GOAL] ID 7 (2026-06-01): Become a team lead within 6 months."
        ),
        "expected_pii": ["ali.hassan@example.com"],
    },
]


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

_DATA_REPLY_PREFIX = "Here are the details on file:\n\n"


def _wrap_result(tool_result: str) -> str:
    return f"{_DATA_REPLY_PREFIX}{tool_result}"


def _pii_preserved(raw_data: str, formatted: str, expected_pii: list[str]) -> bool:
    """Return True when required tokens appear and no contact detail was hallucinated."""
    from app.core.response_formatter import _pii_preserved as no_hallucinated_pii

    for token in expected_pii:
        if token not in formatted:
            return False
    return no_hallucinated_pii(raw_data, formatted)


@dataclass
class SampleResult:
    user_message: str
    latency_off_ms: float = 0.0
    latency_on_ms: Optional[float] = None
    pii_preserved: Optional[bool] = None
    char_delta: Optional[int] = None
    error: str = ""


async def _run_off(sample: dict) -> tuple[str, float]:
    """Run the deterministic path and measure latency."""
    t0 = time.perf_counter()
    reply = _wrap_result(sample["tool_result"])
    elapsed = (time.perf_counter() - t0) * 1000
    return reply, elapsed


async def _run_on(
    sample: dict, provider, deterministic_reply: str
) -> tuple[str, float, bool]:
    """Run the LLM formatting path and measure latency."""
    from app.core.response_formatter import format_data_reply

    t0 = time.perf_counter()
    formatted = await format_data_reply(
        sample["user_message"], deterministic_reply, provider
    )
    elapsed = (time.perf_counter() - t0) * 1000
    raw_data = deterministic_reply.removeprefix(_DATA_REPLY_PREFIX)
    preserved = _pii_preserved(raw_data, formatted, sample["expected_pii"])
    return formatted, elapsed, preserved


def _print_table(results: list[SampleResult], run_llm: bool) -> None:
    col_w = 38

    if run_llm:
        header = (
            f"{'Message':<{col_w}}  {'Off (ms)':>10}  {'On (ms)':>10}  "
            f"{'PII ok':>7}  {'ΔLen':>6}"
        )
        sep = "-" * len(header)
        print(header)
        print(sep)
        for r in results:
            msg = r.user_message[:col_w]
            on_ms = f"{r.latency_on_ms:>10.1f}" if r.latency_on_ms is not None else f"{'n/a':>10}"
            pii = (
                f"{'yes':>7}" if r.pii_preserved
                else f"{'NO':>7}" if r.pii_preserved is False
                else f"{'n/a':>7}"
            )
            delta = f"{r.char_delta:>+6}" if r.char_delta is not None else f"{'n/a':>6}"
            print(f"{msg:<{col_w}}  {r.latency_off_ms:>10.2f}  {on_ms}  {pii}  {delta}")
    else:
        header = f"{'Message':<{col_w}}  {'Off (ms)':>10}"
        sep = "-" * len(header)
        print(header)
        print(sep)
        for r in results:
            msg = r.user_message[:col_w]
            print(f"{msg:<{col_w}}  {r.latency_off_ms:>10.2f}")

    print()


def _print_summary(results: list[SampleResult], run_llm: bool) -> None:
    n = len(results)
    avg_off = sum(r.latency_off_ms for r in results) / n

    print("Summary")
    print("=" * 42)
    print(f"  Samples              : {n}")
    print(f"  Avg latency OFF (ms) : {avg_off:.2f}")

    if run_llm:
        on_results = [r for r in results if r.latency_on_ms is not None]
        if on_results:
            avg_on = sum(r.latency_on_ms for r in on_results) / len(on_results)
            pii_ok = sum(1 for r in on_results if r.pii_preserved)
            pii_pct = 100.0 * pii_ok / len(on_results)
            avg_delta = sum(r.char_delta for r in on_results if r.char_delta is not None) / len(
                on_results
            )
            overhead = avg_on - avg_off

            print(f"  Avg latency ON  (ms) : {avg_on:.1f}")
            print(f"  Avg overhead    (ms) : {overhead:.1f}")
            print(f"  PII preservation (%) : {pii_pct:.0f}")
            print(f"  Avg char delta       : {avg_delta:+.0f}  (negative = shorter)")
        else:
            print("  LLM ON results       : none (all errors)")


async def _main(args: argparse.Namespace) -> None:
    run_llm = not args.no_llm

    # Ensure formatter LLM pass is active (matches production with RESPONSE_FORMATTER_ENABLED=true).
    os.environ.setdefault("RESPONSE_FORMATTER_ENABLED", "true")

    samples = _EVAL_SET[: args.samples]
    results: list[SampleResult] = []

    provider = None
    if run_llm:
        try:
            from app.core.llm_providers.ollama import OllamaProvider
            from app.core.config import settings as cfg

            model = args.model or cfg.ollama_model
            provider = OllamaProvider()
            # Override model if explicitly requested.
            if args.model:
                os.environ["OLLAMA_MODEL"] = args.model
            print(f"LLM formatter: ON  (model={model})")
        except Exception as exc:
            print(f"[warn] Could not initialise Ollama provider: {exc}")
            print("       Running deterministic-only mode.\n")
            run_llm = False
    else:
        print("LLM formatter: OFF (--no-llm)")

    print(f"Samples        : {len(samples)}\n")

    for sample in samples:
        r = SampleResult(user_message=sample["user_message"])

        det_reply, off_ms = await _run_off(sample)
        r.latency_off_ms = off_ms

        if run_llm and provider is not None:
            try:
                formatted, on_ms, pii_ok = await _run_on(sample, provider, det_reply)
                r.latency_on_ms = on_ms
                r.pii_preserved = pii_ok
                r.char_delta = len(formatted) - len(det_reply)
            except Exception as exc:
                r.error = str(exc)

        results.append(r)

    _print_table(results, run_llm)
    _print_summary(results, run_llm)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark LLM response formatter vs deterministic template.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=len(_EVAL_SET),
        help="Number of eval samples to run (max %(default)s).",
    )
    parser.add_argument(
        "--model",
        default=None,
        metavar="MODEL",
        help="Ollama model to use for the formatter (default: OLLAMA_MODEL env / config).",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Run deterministic path only (skip LLM formatting call).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(_main(_parse_args()))
