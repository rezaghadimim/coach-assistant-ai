"""Convert Infinia Life Coach dataset rows into Coach Assistant AI training format.

Each raw Infinia row has:
  - prompt      : a vulnerable emotional statement
  - completion  : a poetic, metaphor-heavy grounding reply
  - topic       : emotional domain (e.g. "self-doubt", "anxiety and overthinking")

Conversion does two things:
1. Wraps the row in the project's messages format (system / user / assistant).
2. Adapts the completion toward coach voice — keeping empathy but adding a
   reflective coaching question or small concrete move, and capping metaphor load.

Two adaptation backends:
  - "template" : fast, deterministic rewriting rules (good for tests and dry runs)
  - "ollama"   : batch rewrite via local Ollama LLM (better quality for real training)
"""

from __future__ import annotations

import json
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Resolved at import time so tests can override before importing this module.
_PROMPTS_MODULE = None


def _get_system_prompt() -> str:
    global _PROMPTS_MODULE
    if _PROMPTS_MODULE is None:
        # Allow running from the scripts/ directory without installing the package.
        root = Path(__file__).resolve().parent.parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from app.core.prompts import COACH_ASSISTANT_SYSTEM_PROMPT  # noqa: PLC0415
        _PROMPTS_MODULE = COACH_ASSISTANT_SYSTEM_PROMPT
    return _PROMPTS_MODULE


# ---------------------------------------------------------------------------
# Template-based adaptation
# ---------------------------------------------------------------------------

# Coaching questions appended after keeping the first sentence of the completion.
_COACHING_QUESTIONS_BY_TOPIC: dict[str, list[str]] = {
    "self-doubt": [
        "What would it feel like to trust yourself in this moment?",
        "When did you last feel confident — what was different then?",
        "What is one small thing you already know how to do well?",
    ],
    "anxiety and overthinking": [
        "What is the one thing you can control right now?",
        "If you set the worry aside for ten minutes, what would you do?",
        "What does your body need most in this moment — rest, movement, or connection?",
    ],
    "fear of change": [
        "What is the smallest step forward you could take today?",
        "What would be possible on the other side of this change?",
        "Who has navigated a similar shift that you could learn from?",
    ],
    "burnout and exhaustion": [
        "What is one thing you could take off your plate this week?",
        "When did you last feel genuinely rested — what made that possible?",
        "What would 'enough' look like for you right now?",
    ],
    "loss of direction": [
        "What matters most to you right now, even if it feels distant?",
        "What did you used to love doing that still calls to you?",
        "If you had permission to move in any direction, what would draw you first?",
    ],
    "forgiveness and self-acceptance": [
        "What would you say to a friend who was carrying this same weight?",
        "What does self-compassion look like in practice for you today?",
        "What is one way you could honour how far you have already come?",
    ],
}
_GENERIC_COACHING_QUESTIONS = [
    "What feels most alive in you when you reflect on this?",
    "What would a small act of courage look like for you this week?",
    "What support do you have around you right now?",
]

# Patterns that indicate heavy metaphor load (nature/sky/wind).
_METAPHOR_PATTERNS = re.compile(
    r"\b(wind|sky|breath|flame|ocean|river|roots?|mountain|cloud|earth|"
    r"star|wave|forest|seed|water|light|dark|stone|fire)\b",
    re.IGNORECASE,
)


def _first_sentence(text: str) -> str:
    """Return the first sentence of a paragraph, stripping trailing whitespace."""
    match = re.match(r"[^.!?]+[.!?]", text)
    return match.group(0).strip() if match else text.split("\n")[0].strip()


def _metaphor_load(text: str) -> int:
    return len(_METAPHOR_PATTERNS.findall(text))


def adapt_completion_template(completion: str, topic: str) -> str:
    """Rewrite a poetic Infinia completion toward coach voice using template rules.

    Strategy:
    - Keep the first sentence (emotional validation, even if metaphorical).
    - If the original has high metaphor load (>3 matches), trim to that one sentence.
    - Append a topic-appropriate coaching question.
    """
    if _metaphor_load(completion) > 3:
        body = _first_sentence(completion)
    else:
        body = completion.strip()
    questions = _COACHING_QUESTIONS_BY_TOPIC.get(topic, _GENERIC_COACHING_QUESTIONS)
    question = random.choice(questions)  # noqa: S311
    return f"{body} {question}"


# ---------------------------------------------------------------------------
# Ollama-based adaptation
# ---------------------------------------------------------------------------

_OLLAMA_ADAPT_PROMPT = """\
You are helping adapt training examples for an AI life coach assistant.

The original completion below is poetic and metaphor-heavy. Rewrite it to:
1. Keep the warmth and emotional validation (one sentence is fine).
2. Add 1-2 coaching moves: a reflective question, a GROW framing, or a small concrete step.
3. Use at most one light metaphor.
4. Keep it concise (2-4 sentences total).
5. Do NOT use clinical language or give medical advice.

Topic: {topic}
Original: {completion}

Rewrite:"""


def adapt_completion_ollama(
    completion: str,
    topic: str,
    ollama_base_url: str = "http://localhost:11434",
    model: str = "llama3.1:8b",
) -> str:
    """Rewrite a completion using a local Ollama model."""
    try:
        import httpx  # noqa: PLC0415
    except ImportError:
        raise ImportError("httpx is required for ollama adaptation. pip install httpx")

    prompt = _OLLAMA_ADAPT_PROMPT.format(topic=topic, completion=completion)
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.4, "num_predict": 256},
    }
    try:
        resp = httpx.post(
            f"{ollama_base_url}/api/generate",
            json=payload,
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json()["response"].strip()
    except Exception:
        # Fall back to template adaptation so a single Ollama hiccup does not abort.
        return adapt_completion_template(completion, topic)


# ---------------------------------------------------------------------------
# Record conversion
# ---------------------------------------------------------------------------

@dataclass
class ConvertStats:
    total: int = 0
    train: int = 0
    val: int = 0
    holdout: int = 0
    skipped: int = 0


def row_to_record(
    row: dict,
    split: str,
    adapt_backend: str = "template",
    ollama_base_url: str = "http://localhost:11434",
    ollama_model: str = "llama3.1:8b",
) -> dict:
    """Convert one Infinia row to a training record with metadata."""
    topic = row.get("topic", "")
    if adapt_backend == "ollama":
        assistant_content = adapt_completion_ollama(
            row["completion"], topic, ollama_base_url, ollama_model
        )
    else:
        assistant_content = adapt_completion_template(row["completion"], topic)

    return {
        "messages": [
            {"role": "system", "content": _get_system_prompt()},
            {"role": "user", "content": row["prompt"].strip()},
            {"role": "assistant", "content": assistant_content},
        ],
        "metadata": {
            "topic": topic,
            "source": "infinia",
            "split": split,
            "original_completion": row["completion"],
        },
    }


def convert_dataset(
    raw_path: Path,
    output_dir: Path,
    *,
    train_ratio: float = 0.90,
    val_ratio: float = 0.05,
    seed: int = 42,
    adapt_backend: str = "template",
    ollama_base_url: str = "http://localhost:11434",
    ollama_model: str = "llama3.1:8b",
    sample: int | None = None,
) -> ConvertStats:
    """Read raw.jsonl, adapt completions, split, and write train/val/holdout JSONL files."""
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    with raw_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    if sample is not None:
        rng = random.Random(seed)
        rows = rng.sample(rows, min(sample, len(rows)))

    rng = random.Random(seed)
    rng.shuffle(rows)

    total = len(rows)
    n_val = max(1, round(total * val_ratio))
    n_holdout = max(1, round(total * (1 - train_ratio - val_ratio)))

    splits = (
        [("holdout", rows[:n_holdout])]
        + [("val", rows[n_holdout : n_holdout + n_val])]
        + [("train", rows[n_holdout + n_val :])]
    )

    stats = ConvertStats(total=total)
    file_handles = {
        "train": (output_dir / "infinia_train.jsonl").open("w", encoding="utf-8"),
        "val": (output_dir / "infinia_val.jsonl").open("w", encoding="utf-8"),
        "holdout": (output_dir / "infinia_holdout.jsonl").open("w", encoding="utf-8"),
    }

    # Also write a combined adapted file for the merge script.
    adapted_fh = (output_dir / "infinia_adapted.jsonl").open("w", encoding="utf-8")
    raw_adapted_fh = (output_dir / "infinia_raw_adapted.jsonl").open("w", encoding="utf-8")

    try:
        for split_name, split_rows in splits:
            for row in split_rows:
                try:
                    record = row_to_record(
                        row,
                        split_name,
                        adapt_backend=adapt_backend,
                        ollama_base_url=ollama_base_url,
                        ollama_model=ollama_model,
                    )
                except Exception:
                    stats.skipped += 1
                    continue

                line_str = json.dumps(record, ensure_ascii=False) + "\n"
                file_handles[split_name].write(line_str)
                if split_name in ("train", "val"):
                    adapted_fh.write(line_str)
                raw_adapted_fh.write(line_str)

                if split_name == "train":
                    stats.train += 1
                elif split_name == "val":
                    stats.val += 1
                else:
                    stats.holdout += 1
    finally:
        for fh in file_handles.values():
            fh.close()
        adapted_fh.close()
        raw_adapted_fh.close()

    return stats
