"""Compare RAG retrieval quality before vs after recent improvements.

BEFORE snapshot (from git HEAD):
  - Original code (no off-topic gate, no hybrid RRF, plain chunking)
  - Only docs/knowledge/sample.md indexed
  - Original 20-question eval set
  - RAG_MIN_SCORE=0.15, RAG_TOP_K=3, RAG_RETRIEVE_K=25, rerank off

AFTER snapshot (current working tree):
  - All code + knowledge + eval changes
  - Full coaching knowledge base
  - Expanded 32-question eval set (+ same original 20 for apples-to-apples)

Usage:
    PYTHONPATH=. python scripts/benchmark_rag_before_after.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class EvalMetrics:
    label: str
    total: int
    passed: int
    abstain_pass: int
    abstain_total: int
    recall_pass: int
    recall_total: int
    chunks_indexed: int

    @property
    def accuracy(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def abstain_rate(self) -> float:
        return self.abstain_pass / self.abstain_total if self.abstain_total else 0.0

    @property
    def recall_rate(self) -> float:
        return self.recall_pass / self.recall_total if self.recall_total else 0.0


def _run_eval(
    *,
    label: str,
    eval_file: Path,
    env: dict[str, str],
    knowledge_dir: Path,
) -> EvalMetrics:
    """Run retrieval eval in a subprocess with isolated env."""
    script = ROOT / "scripts" / "eval_rag_grounding.py"
    merged_env = {**os.environ, **env, "RAG_KNOWLEDGE_STARTER_DIR": str(knowledge_dir)}
    proc = subprocess.run(
        [sys.executable, str(script), "--eval-file", str(eval_file), "--backend", "token"],
        cwd=ROOT,
        env=merged_env,
        capture_output=True,
        text=True,
    )
    if proc.returncode not in (0, 1):
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        proc.check_returncode()

    stdout = proc.stdout
    total = passed = abstain_pass = abstain_total = recall_pass = recall_total = 0
    chunks_indexed = 0
    import re
    for line in stdout.splitlines():
        if line.startswith("Index built:"):
            chunks_indexed = int(line.split(":")[1].strip().split()[0])
        m_total = re.search(r"Total:\s+(\d+)\s+Passed:\s+(\d+)", line)
        if m_total:
            total = int(m_total.group(1))
            passed = int(m_total.group(2))
        if line.strip().startswith("Abstain") and "no rows" not in line:
            cols = line.split()
            if len(cols) >= 4 and cols[1].isdigit():
                abstain_pass = int(cols[1])
                abstain_total = int(cols[2])
        if line.strip().startswith("Recall") and "no rows" not in line:
            cols = line.split()
            if len(cols) >= 4 and cols[1].isdigit():
                recall_pass = int(cols[1])
                recall_total = int(cols[2])

    return EvalMetrics(
        label=label,
        total=total,
        passed=passed,
        abstain_pass=abstain_pass,
        abstain_total=abstain_total,
        recall_pass=recall_pass,
        recall_total=recall_total,
        chunks_indexed=chunks_indexed,
    )


def _git_show(relpath: str) -> bytes:
    return subprocess.check_output(["git", "show", f"HEAD:{relpath}"], cwd=ROOT)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="rag_bench_"))
    try:
        # --- BEFORE setup ---
        before_eval = tmp / "eval_before.jsonl"
        before_eval.write_bytes(_git_show("data/eval/rag_grounding.jsonl"))

        before_knowledge = tmp / "knowledge_before"
        before_knowledge.mkdir()
        (before_knowledge / "sample.md").write_bytes(_git_show("docs/knowledge/sample.md"))

        before_code = tmp / "code_before"
        before_code.mkdir()
        for rel in (
            "app/rag/retriever.py",
            "app/rag/ingest.py",
            "app/core/scope.py",
            "app/core/config.py",
        ):
            dest = before_code / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(_git_show(rel))

        before_env = {
            "RAG_MIN_SCORE": "0.15",
            "RAG_TOP_K": "3",
            "RAG_RETRIEVE_K": "25",
            "RAG_RERANK_ENABLED": "false",
            "RAG_HYBRID_RRF_ENABLED": "false",
            "PYTHONPATH": f"{before_code}{os.pathsep}{ROOT}",
        }

        print("Running BEFORE benchmark (git HEAD code, sample.md only)...")
        before = _run_eval(
            label="BEFORE",
            eval_file=before_eval,
            env=before_env,
            knowledge_dir=before_knowledge,
        )

        # --- AFTER setup ---
        after_env = {
            "RAG_MIN_SCORE": "0.15",
            "RAG_TOP_K": "2",
            "RAG_RETRIEVE_K": "30",
            "RAG_RERANK_MIN_SCORE": "0.42",
            "RAG_RERANK_ENABLED": "false",
            "RAG_HYBRID_RRF_ENABLED": "true",
            "PYTHONPATH": str(ROOT),
        }

        print("Running AFTER benchmark (full knowledge, expanded eval)...")
        after_full = _run_eval(
            label="AFTER (32 Q)",
            eval_file=ROOT / "data/eval/rag_grounding.jsonl",
            env=after_env,
            knowledge_dir=ROOT / "docs/knowledge",
        )

        print("Running AFTER benchmark (original 20 Q, apples-to-apples)...")
        after_20 = _run_eval(
            label="AFTER (20 Q)",
            eval_file=before_eval,
            env=after_env,
            knowledge_dir=ROOT / "docs/knowledge",
        )

        # --- Report ---
        rows = [before, after_20, after_full]
        print()
        print("=" * 78)
        print(f"{'Scenario':<22} {'Chunks':>7} {'Accuracy':>9} {'Abstain':>10} {'Recall':>10}")
        print("-" * 78)
        for m in rows:
            print(
                f"{m.label:<22} {m.chunks_indexed:>7} "
                f"{m.accuracy:>8.1%} "
                f"{m.abstain_pass}/{m.abstain_total} ({m.abstain_rate:>5.0%}) "
                f"{m.recall_pass}/{m.recall_total} ({m.recall_rate:>5.0%})"
            )
        print("=" * 78)
        print()
        print("Notes:")
        print("  BEFORE = git HEAD code, only sample.md, original 20 eval questions")
        print("  AFTER (20 Q) = same 20 questions with all improvements + full knowledge")
        print("  AFTER (32 Q) = expanded eval set including new coaching/off-topic cases")
        print("  Rerank disabled in both runs for fast offline comparison (token backend).")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
