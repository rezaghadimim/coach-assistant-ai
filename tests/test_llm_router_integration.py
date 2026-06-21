"""Live regression guard for LLM-router abstention (optional, needs Ollama).

Runs the real router (``settings.ollama_model``) over the labeled eval set and
asserts the two properties this work established:

  - overall accuracy >= 0.90 (the doc target), and
  - hallucination rate <= 0.10 — i.e. the router almost never assigns a tool to
    a general coaching question (baseline before prompt hardening was 0.47).

Measured baseline on llama3.1:8b after hardening: accuracy 95.1%, hallucination
rate 0.0%.  Skipped automatically when Ollama is unreachable or the configured
model is not pulled, so it never breaks offline CI.  Force-require with
``RUN_LLM_ROUTER_INTEGRATION=1`` to turn a skip into a failure.
"""

from __future__ import annotations

import asyncio
import json
import os
import unittest
from pathlib import Path

from app.core.config import settings

_EVAL_PATH = Path("data/eval/llm_router.jsonl")
_NONE = "none"
_MIN_ACCURACY = 0.90
_MAX_HALLUCINATION_RATE = 0.10


def _force_required() -> bool:
    return os.environ.get("RUN_LLM_ROUTER_INTEGRATION", "").lower() in {"1", "true", "yes"}


def _skip_reason() -> str:
    import httpx

    try:
        resp = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=3.0)
        resp.raise_for_status()
        names = {m.get("name", "") for m in resp.json().get("models", [])}
    except Exception as exc:  # unreachable / timeout / bad response
        return f"Ollama unreachable at {settings.ollama_base_url} ({type(exc).__name__})"

    model = settings.ollama_model
    if model not in names and f"{model}:latest" not in names:
        return f"router model {model!r} not pulled in Ollama"
    return ""


_SKIP = "" if _force_required() else _skip_reason()


@unittest.skipIf(bool(_SKIP), _SKIP or "skipped")
class LlmRouterAbstentionRegressionTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(_EVAL_PATH, encoding="utf-8") as fh:
            cls.rows = [json.loads(line) for line in fh if line.strip()]

    async def _predict_all(self) -> list[str]:
        from app.core.llm_providers.ollama import OllamaProvider
        from app.core.llm_router import classify_tool_llm

        provider = OllamaProvider()
        sem = asyncio.Semaphore(4)

        async def predict(utterance: str) -> str:
            async with sem:
                match = await classify_tool_llm(utterance, provider=provider)
            return match.tool if match is not None else _NONE

        return await asyncio.gather(*(predict(r["utterance"]) for r in self.rows))

    async def test_accuracy_and_no_hallucination(self) -> None:
        predictions = await self._predict_all()

        correct = sum(
            pred == row["expected_tool"]
            for pred, row in zip(predictions, self.rows)
        )
        none_rows = [r for r in self.rows if r["expected_tool"] == _NONE]
        hallucinated = sum(
            pred != _NONE
            for pred, row in zip(predictions, self.rows)
            if row["expected_tool"] == _NONE
        )

        accuracy = correct / len(self.rows)
        halluc_rate = hallucinated / len(none_rows) if none_rows else 0.0

        self.assertGreaterEqual(
            accuracy, _MIN_ACCURACY,
            f"router accuracy {accuracy:.2%} regressed below {_MIN_ACCURACY:.0%}",
        )
        self.assertLessEqual(
            halluc_rate, _MAX_HALLUCINATION_RATE,
            f"router hallucination rate {halluc_rate:.2%} exceeds "
            f"{_MAX_HALLUCINATION_RATE:.0%} — it is assigning tools to coaching questions",
        )


if __name__ == "__main__":
    unittest.main()
