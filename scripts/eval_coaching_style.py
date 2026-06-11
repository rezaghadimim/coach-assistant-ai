"""Evaluate coaching style across one or more Ollama model variants.

Compares baseline vs fine-tuned models on empathy, practicality, metaphor load,
and response length — without requiring a GPU or a separate judge model.

Usage:
    python scripts/eval_coaching_style.py
    python scripts/eval_coaching_style.py --models baseline,coach-assistant-infinia
    python scripts/eval_coaching_style.py --models baseline --eval-file data/eval/coaching_empathy.jsonl
    python scripts/eval_coaching_style.py --models baseline,coach-assistant-infinia --judge-model openai/gpt-4o-mini

Scoring (heuristics — no GPU required):
    empathy        : presence of validation phrases and reflective language
    practicality   : questions, numbered steps, coaching framework mentions
    metaphor_load  : nature/sky/wind metaphor density (Infinia overfit signal)
    length         : whether response fits the 2-5 paragraph target

Exit code 1 when guardrail practicality drops below --min-practicality.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ---------------------------------------------------------------------------
# Rubric patterns
# ---------------------------------------------------------------------------

_EMPATHY_PATTERNS = re.compile(
    r"\b(I hear you|I understand|that sounds|that must be|it makes sense|"
    r"I can imagine|what you('re| are) feeling|you('re| are) not alone|"
    r"valid|acknowledged|seen|heard|sitting with)\b",
    re.IGNORECASE,
)

_PRACTICALITY_PATTERNS = re.compile(
    r"\b(what would|what if|what is|what does|what might|"
    r"how (might|could|would|do)|when did|tell me more|"
    r"GROW|goal|reality|options|will|SMART|specific|measurable|"
    r"action (step|item|plan)|next step|this week|by (monday|friday|end of)|"
    r"1\.|2\.|3\.|first|second|third|numbered|framework|strategy|"
    r"exercise|technique|practice)\b",
    re.IGNORECASE,
)

_METAPHOR_PATTERNS = re.compile(
    r"\b(wind|sky|breath|flame|ocean|river|roots?|mountain|cloud|earth|"
    r"star|wave|forest|seed|water flows?|light|stone|fire|sun|moon|"
    r"the (wind|sky|earth|flame|ocean|river))\b",
    re.IGNORECASE,
)

_QUESTION_PATTERN = re.compile(r"\?")


def score_response(text: str) -> dict[str, float]:
    """Score a response text on four dimensions, each 0.0–1.0."""
    empathy_hits = len(_EMPATHY_PATTERNS.findall(text))
    empathy = min(1.0, empathy_hits / 2.0)

    practicality_hits = len(_PRACTICALITY_PATTERNS.findall(text))
    question_count = len(_QUESTION_PATTERN.findall(text))
    practicality = min(1.0, (practicality_hits + question_count) / 4.0)

    metaphor_hits = len(_METAPHOR_PATTERNS.findall(text))
    metaphor_load = min(1.0, metaphor_hits / 6.0)

    # Length score: target is roughly 100–600 words (2–5 paragraphs).
    word_count = len(text.split())
    if 80 <= word_count <= 700:
        length_score = 1.0
    elif word_count < 80:
        length_score = word_count / 80.0
    else:
        length_score = max(0.0, 1.0 - (word_count - 700) / 300.0)

    return {
        "empathy": round(empathy, 3),
        "practicality": round(practicality, 3),
        "metaphor_load": round(metaphor_load, 3),
        "length": round(length_score, 3),
    }


# ---------------------------------------------------------------------------
# Ollama client
# ---------------------------------------------------------------------------

def _ollama_chat(
    prompt: str,
    model: str,
    ollama_base_url: str,
    system_prompt: str,
) -> str:
    try:
        import httpx  # noqa: PLC0415
    except ImportError:
        print("ERROR: httpx not installed. pip install httpx", file=sys.stderr)
        sys.exit(1)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.0},
    }
    try:
        resp = httpx.post(
            f"{ollama_base_url}/api/chat",
            json=payload,
            timeout=120.0,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()
    except Exception as exc:
        return f"[ERROR: {exc}]"


# ---------------------------------------------------------------------------
# OpenRouter judge (optional)
# ---------------------------------------------------------------------------

def _judge_response(
    prompt: str,
    response: str,
    judge_model: str,
    openrouter_key: str,
) -> dict[str, float] | None:
    """Use an LLM judge for a richer empathy+practicality score (0–1 each)."""
    try:
        import httpx  # noqa: PLC0415
    except ImportError:
        return None

    judge_prompt = (
        f"Score this AI coaching response on two dimensions (0.0 to 1.0):\n"
        f"1. empathy — warmth, validation, emotional attunement\n"
        f"2. practicality — coaching moves: questions, GROW, action steps\n\n"
        f"User said: {prompt}\n\n"
        f"Response: {response}\n\n"
        f'Reply with JSON only: {{"empathy": <float>, "practicality": <float>}}'
    )
    try:
        resp = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {openrouter_key}"},
            json={
                "model": judge_model,
                "messages": [{"role": "user", "content": judge_prompt}],
                "temperature": 0.0,
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        # Extract JSON from the response.
        match = re.search(r"\{[^}]+\}", content)
        if match:
            return json.loads(match.group(0))
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Eval runner
# ---------------------------------------------------------------------------

def load_eval_set(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def run_eval(
    models: list[str],
    eval_rows: list[dict],
    system_prompt: str,
    ollama_base_url: str,
    judge_model: str | None,
    openrouter_key: str | None,
) -> dict[str, list[dict]]:
    """Run all prompts against all models. Returns {model: [scored_rows]}."""
    results: dict[str, list[dict]] = {m: [] for m in models}

    total = len(models) * len(eval_rows)
    done = 0

    for model in models:
        for row in eval_rows:
            done += 1
            print(f"\r  [{done}/{total}] {model} — {row['id']}…", end="", flush=True)

            response = _ollama_chat(row["prompt"], model, ollama_base_url, system_prompt)
            heuristic_scores = score_response(response)

            judge_scores = None
            if judge_model and openrouter_key:
                judge_scores = _judge_response(row["prompt"], response, judge_model, openrouter_key)

            scored = {
                **row,
                "response": response,
                "scores": heuristic_scores,
            }
            if judge_scores:
                scored["judge_scores"] = judge_scores

            results[model].append(scored)

    print()
    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _bucket_summary(rows: list[dict]) -> dict[str, dict[str, float]]:
    by_bucket: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_bucket[row["bucket"]].append(row)

    summary = {}
    for bucket, bucket_rows in by_bucket.items():
        dims = ["empathy", "practicality", "metaphor_load", "length"]
        summary[bucket] = {
            d: round(_avg([r["scores"][d] for r in bucket_rows]), 3) for d in dims
        }
    return summary


def _print_report(results: dict[str, list[dict]]) -> None:
    models = list(results.keys())
    dims = ["empathy", "practicality", "metaphor_load", "length"]

    print("\n=== Coaching Style Evaluation ===\n")
    print(f"{'Model':<35} {'empathy':>8} {'pract.':>8} {'metaphor':>9} {'length':>7}")
    print("-" * 70)

    for model in models:
        rows = results[model]
        avgs = {d: round(_avg([r["scores"][d] for r in rows]), 3) for d in dims}
        print(
            f"{model:<35} {avgs['empathy']:>8.3f} {avgs['practicality']:>8.3f} "
            f"{avgs['metaphor_load']:>9.3f} {avgs['length']:>7.3f}"
        )

    print()
    for model in models:
        summary = _bucket_summary(results[model])
        print(f"  {model} by bucket:")
        for bucket, scores in sorted(summary.items()):
            print(
                f"    {bucket:<12} empathy={scores['empathy']:.3f}  "
                f"pract={scores['practicality']:.3f}  "
                f"metaphor={scores['metaphor_load']:.3f}"
            )
        print()


def _save_results(results: dict[str, list[dict]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)
    print(f"Full results saved to {output_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    from app.core.config import settings  # noqa: PLC0415
    from app.core.prompts import COACH_ASSISTANT_SYSTEM_PROMPT  # noqa: PLC0415

    parser = argparse.ArgumentParser(
        description="Evaluate coaching style across Ollama model variants"
    )
    parser.add_argument(
        "--models",
        default="baseline",
        help=(
            "Comma-separated Ollama model names to evaluate. "
            "Use 'baseline' as an alias for the current OLLAMA_MODEL setting. "
            "(default: baseline)"
        ),
    )
    parser.add_argument(
        "--eval-file",
        default="data/eval/coaching_empathy.jsonl",
        help="Path to eval JSONL (default: data/eval/coaching_empathy.jsonl)",
    )
    parser.add_argument(
        "--ollama-base-url",
        default=settings.ollama_base_url,
        help=f"Ollama base URL (default: {settings.ollama_base_url})",
    )
    parser.add_argument(
        "--output",
        default="artifacts/eval/coaching_style_results.json",
        help="Path to write full scored results JSON (default: artifacts/eval/coaching_style_results.json)",
    )
    parser.add_argument(
        "--judge-model",
        default=None,
        help="Optional OpenRouter model for LLM-as-judge (e.g. openai/gpt-4o-mini)",
    )
    parser.add_argument(
        "--min-practicality",
        type=float,
        default=0.0,
        help="Exit non-zero if guardrail bucket practicality falls below this value (default: 0.0)",
    )
    parser.add_argument(
        "--show-responses",
        action="store_true",
        help="Print each model response in full",
    )
    args = parser.parse_args()

    eval_path = Path(args.eval_file)
    if not eval_path.exists():
        print(f"ERROR: eval file not found: {eval_path}", file=sys.stderr)
        return 1

    eval_rows = load_eval_set(eval_path)
    if not eval_rows:
        print("ERROR: eval file is empty.", file=sys.stderr)
        return 1

    # Resolve "baseline" alias.
    model_names = []
    for name in args.models.split(","):
        name = name.strip()
        model_names.append(settings.ollama_model if name == "baseline" else name)

    openrouter_key = (
        os.environ.get("OPENROUTER_API_KEY") or getattr(settings, "openrouter_api_key", None)
    ) if args.judge_model else None

    print(f"Evaluating {len(model_names)} model(s) on {len(eval_rows)} prompts…")
    for name in model_names:
        print(f"  - {name}")

    results = run_eval(
        model_names,
        eval_rows,
        COACH_ASSISTANT_SYSTEM_PROMPT,
        args.ollama_base_url,
        args.judge_model,
        openrouter_key,
    )

    _print_report(results)
    _save_results(results, Path(args.output))

    if args.show_responses:
        for model, rows in results.items():
            print(f"\n=== {model} ===")
            for row in rows:
                print(f"\n[{row['bucket']}] {row['id']}: {row['prompt']}")
                print(f"Response: {row['response']}")
                print(f"Scores: {row['scores']}")

    # Guardrail check.
    if args.min_practicality > 0.0:
        for model, rows in results.items():
            guardrail_rows = [r for r in rows if r["bucket"] == "guardrail"]
            if guardrail_rows:
                avg_pract = _avg([r["scores"]["practicality"] for r in guardrail_rows])
                if avg_pract < args.min_practicality:
                    print(
                        f"\nFAIL: {model} guardrail practicality {avg_pract:.3f} "
                        f"< required {args.min_practicality:.3f}",
                        file=sys.stderr,
                    )
                    return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
