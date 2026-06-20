"""Benchmark the per-tool deterministic formatter fast path (tool/hint routing).

This complements ``benchmark_response_formatter.py`` (which only compares the
deterministic *template* against the LLM pass). It measures the path added by
the routing-metadata work: when ``format_data_reply`` receives ``tool``/``hint``,
:func:`try_deterministic_tool_format` can produce the final human-friendly reply
*without an LLM call at all*.

Metrics per sample:
  det_hit        Whether the per-tool deterministic formatter handled the reply
  det_us         Deterministic formatting latency (microseconds)
  llm_ms         LLM formatting latency for the same reply (Ollama; for contrast)
  pii_ok         All expected PII present AND nothing hallucinated

Summary highlights the win: % of common reply shapes now resolved deterministically,
the latency avoided per hit, and PII preservation on the deterministic path.

Usage:
    python scripts/benchmark_formatter_hints.py
    python scripts/benchmark_formatter_hints.py --no-llm   # skip Ollama contrast
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_DATA_REPLY_PREFIX = "Here are the details on file:\n\n"


# Each entry mirrors what the fast path resolves: a raw tool result plus the
# routing metadata (tool + optional hint) that classify_tool / the KB attach.
_EVAL_SET = [
    {
        "user_message": "What is Ali's email?",
        "tool": "get_client",
        "hint": "profile:email",
        "tool_result": (
            "Client ID: ali\nName: Ali Hassan\nEmail: ali.hassan@example.com\n"
            "Phone: (not set)\nAge: 32\nOccupation: Software Engineer\nBackground: (not set)"
        ),
        "expected_pii": ["ali.hassan@example.com"],
    },
    {
        "user_message": "What's Sara's age?",
        "tool": "get_client",
        "hint": "profile:age",
        "tool_result": (
            "Client ID: sara\nName: Sara Karimi\nEmail: (not set)\n"
            "Phone: (not set)\nAge: 28\nOccupation: Marketing Manager\nBackground: (not set)"
        ),
        "expected_pii": [],
    },
    {
        "user_message": "Who are my clients?",
        "tool": "list_clients",
        "hint": None,
        "tool_result": (
            "Registered clients:\n"
            "- Ali Hassan (ID: ali, Email: ali@example.com)\n"
            "- Sara Karimi (ID: sara, Email: sara@example.com)"
        ),
        "expected_pii": [],
    },
    {
        "user_message": "Show Ali's notes",
        "tool": "list_client_notes",
        "hint": None,
        # Dates here used to be misread as phone numbers by the PII validator.
        "tool_result": (
            "- [GOAL] Leadership plan (2026-05-20)\n"
            "  Complete certification by Q3\n"
            "- [STORY] Referral (2026-04-01)\n"
            "  Joined via wellness programme"
        ),
        "expected_pii": [],
    },
    {
        "user_message": "Show Reza's notes",
        "tool": "list_client_notes",
        "hint": None,
        "tool_result": (
            "- [DECISION] Left corporate job (2026-02-05)\n"
            "  Resigned to focus on the startup; reachable on 09121234567"
        ),
        "expected_pii": ["09121234567"],  # a real phone amid ISO dates
    },
]


@dataclass
class Row:
    user_message: str
    det_hit: bool = False
    det_us: float = 0.0
    llm_ms: Optional[float] = None
    pii_ok: Optional[bool] = None


def _wrap(tool_result: str) -> str:
    return f"{_DATA_REPLY_PREFIX}{tool_result}"


def _pii_ok(raw_data: str, formatted: str, expected: list[str]) -> bool:
    from app.core.response_formatter import _pii_preserved as no_hallucinated

    if any(tok not in formatted for tok in expected):
        return False
    return no_hallucinated(raw_data, formatted)


async def _main(args: argparse.Namespace) -> None:
    from app.core.response_formatter import try_deterministic_tool_format

    run_llm = not args.no_llm
    provider = None
    if run_llm:
        try:
            from app.core.config import settings as cfg
            from app.core.llm_providers.ollama import OllamaProvider

            provider = OllamaProvider()
            print(f"LLM contrast : ON  (model={cfg.ollama_model})")
        except Exception as exc:  # pragma: no cover - environment dependent
            print(f"[warn] Ollama unavailable ({exc}); deterministic-only.")
            run_llm = False
    else:
        print("LLM contrast : OFF (--no-llm)")
    print(f"Samples      : {len(_EVAL_SET)}\n")

    rows: list[Row] = []
    for s in _EVAL_SET:
        raw = s["tool_result"]
        row = Row(user_message=s["user_message"])

        # Deterministic per-tool path (the new fast path).
        t0 = time.perf_counter()
        det = try_deterministic_tool_format(
            s["user_message"], raw, tool=s["tool"], hint=s["hint"]
        )
        row.det_us = (time.perf_counter() - t0) * 1e6
        row.det_hit = det is not None
        if det is not None:
            row.pii_ok = _pii_ok(raw, det, s["expected_pii"])

        # Contrast: the LLM formatting pass for the same reply.
        if run_llm and provider is not None:
            from app.core.response_formatter import format_data_reply

            t0 = time.perf_counter()
            try:
                await format_data_reply(s["user_message"], _wrap(raw), provider)
                row.llm_ms = (time.perf_counter() - t0) * 1000
            except Exception:
                row.llm_ms = None

        rows.append(row)

    # ---- table ----
    w = 30
    print(f"{'Message':<{w}}  {'det hit':>7}  {'det µs':>8}  {'llm ms':>8}  {'PII':>5}")
    print("-" * (w + 36))
    for r in rows:
        hit = "yes" if r.det_hit else "no"
        llm = f"{r.llm_ms:>8.1f}" if r.llm_ms is not None else f"{'n/a':>8}"
        pii = "yes" if r.pii_ok else ("NO" if r.pii_ok is False else "n/a")
        print(
            f"{r.user_message[:w]:<{w}}  {hit:>7}  {r.det_us:>8.1f}  {llm}  {pii:>5}"
        )

    # ---- summary ----
    n = len(rows)
    hits = [r for r in rows if r.det_hit]
    hit_rate = 100.0 * len(hits) / n
    avg_det_us = sum(r.det_us for r in hits) / len(hits) if hits else 0.0
    pii_hits = [r for r in hits if r.pii_ok]
    pii_rate = 100.0 * len(pii_hits) / len(hits) if hits else 0.0

    print("\nSummary")
    print("=" * 46)
    print(f"  Samples                   : {n}")
    print(f"  Deterministic hit-rate    : {hit_rate:.0f}%  ({len(hits)}/{n})")
    print(f"  Avg deterministic latency : {avg_det_us:.1f} µs")
    print(f"  PII preserved on hits     : {pii_rate:.0f}%")

    llm_rows = [r for r in rows if r.llm_ms is not None]
    if llm_rows:
        avg_llm = sum(r.llm_ms for r in llm_rows) / len(llm_rows)
        # Latency avoided: deterministic hits would otherwise have paid the LLM cost.
        saved = [r.llm_ms - r.det_us / 1000 for r in hits if r.llm_ms is not None]
        avg_saved = sum(saved) / len(saved) if saved else 0.0
        print(f"  Avg LLM latency (contrast): {avg_llm:.1f} ms")
        print(f"  Avg latency saved per hit : {avg_saved:.1f} ms")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Benchmark per-tool deterministic formatting (tool/hint fast path).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--no-llm", action="store_true", help="Skip the Ollama contrast run.")
    return p.parse_args()


if __name__ == "__main__":
    os.environ.setdefault("RESPONSE_FORMATTER_ENABLED", "true")
    asyncio.run(_main(_parse_args()))
