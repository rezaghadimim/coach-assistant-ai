"""Evaluate RAG retrieval grounding quality.

Tests two things:
  1. Abstention — out-of-domain queries (off-topic, non-coaching) must NOT
     produce any chunks above the configured min_score floor.  If chunks leak
     through, the LLM will be primed to hallucinate "facts" from random content.

  2. Recall — in-corpus coaching questions SHOULD return at least one chunk.
     Optionally, keywords expected in the retrieved text are checked.

Usage:
    python scripts/eval_rag_grounding.py
    python scripts/eval_rag_grounding.py --eval-file data/eval/rag_grounding.jsonl
    python scripts/eval_rag_grounding.py --min-score 0.30
    python scripts/eval_rag_grounding.py --show-failures
    python scripts/eval_rag_grounding.py --min-accuracy 0.85 --exit-nonzero

The eval intentionally works at the retrieval layer only (no LLM call) so it
runs fast and without requiring Ollama to be running.  Use the token backend
(default) for offline CI; pass --backend embedding to test the dense path.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate RAG retrieval grounding.")
    parser.add_argument(
        "--eval-file",
        default="data/eval/rag_grounding.jsonl",
        help="Path to the grounding eval JSONL file.",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=None,
        help="Override RAG_MIN_SCORE for this run.",
    )
    parser.add_argument(
        "--backend",
        choices=["token", "embedding", "auto"],
        default=None,
        help="Override RAG_BACKEND for this run.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of chunks to retrieve per query (default 5).",
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
        "--show-failures",
        action="store_true",
        help="Print failing queries.",
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


def main() -> int:
    args = _parse_args()

    # Apply overrides before importing settings-dependent modules.
    if args.min_score is not None:
        os.environ["RAG_MIN_SCORE"] = str(args.min_score)
    if args.backend is not None:
        os.environ["RAG_BACKEND"] = args.backend

    from app.core.config import settings
    from app.core.knowledge_paths import knowledge_ingest_summary, knowledge_private_dir_if_exists, knowledge_starter_dir
    from app.rag.ingest import ingest_documents_from_dirs
    from app.rag.retriever import index_chunks, retrieve

    starter_dir = str(knowledge_starter_dir())
    private_dir = knowledge_private_dir_if_exists()
    private_str = str(private_dir) if private_dir is not None else None

    print(f"Ingesting from: {knowledge_ingest_summary()}")
    chunks = ingest_documents_from_dirs(
        starter_dir,
        private_str,
        chunk_size=settings.rag_chunk_size,
        chunk_overlap=settings.rag_chunk_overlap,
    )
    indexed = index_chunks(
        chunks,
        embed=(settings.rag_backend != "token"),
        cache_path=settings.rag_index_cache_path,
    )
    print(f"Index built: {indexed} chunks\n")

    eval_path = Path(args.eval_file)
    if not eval_path.exists():
        print(f"ERROR: eval file not found: {eval_path}", file=sys.stderr)
        return 1

    rows = _load_eval_set(str(eval_path))
    if not rows:
        print("ERROR: eval file is empty.", file=sys.stderr)
        return 1

    print(f"Eval set: {eval_path} ({len(rows)} examples)")
    print(f"min_score={settings.rag_min_score}  backend={settings.rag_backend}\n")

    total = len(rows)
    passed = 0
    failures: list[tuple[str, str, str]] = []

    for row in rows:
        question: str = row["question"]
        must_abstain: bool = row.get("must_abstain", False)
        keywords: list[str] = row.get("keywords") or []

        chunks_retrieved = retrieve(
            question,
            top_k=args.top_k,
            min_score=settings.rag_min_score,
            backend=settings.rag_backend,  # type: ignore[arg-type]
        )

        if must_abstain:
            # Expect zero chunks — nothing should clear the floor for off-topic queries.
            if not chunks_retrieved:
                passed += 1
            else:
                best_score = max(c.score for c in chunks_retrieved)
                failures.append((
                    question,
                    "abstain",
                    f"LEAKED {len(chunks_retrieved)} chunk(s), best_score={best_score:.3f}",
                ))
        else:
            # Expect at least one chunk returned.
            if not chunks_retrieved:
                failures.append((question, "recall", "NO chunks retrieved"))
                continue

            if not keywords:
                passed += 1
                continue

            # Optional keyword check: at least one keyword must appear in any retrieved chunk.
            combined_text = " ".join(c.text for c in chunks_retrieved).lower()
            matched_kw = [kw for kw in keywords if kw.lower() in combined_text]
            if matched_kw:
                passed += 1
            else:
                failures.append((
                    question,
                    "keyword",
                    f"no keyword matched {keywords!r} in {len(chunks_retrieved)} chunk(s)",
                ))

    accuracy = passed / total if total > 0 else 0.0
    abstain_rows = [r for r in rows if r.get("must_abstain")]
    recall_rows = [r for r in rows if not r.get("must_abstain")]

    abstain_pass = sum(
        1 for r in abstain_rows
        if not retrieve(
            r["question"],
            top_k=args.top_k,
            min_score=settings.rag_min_score,
            backend=settings.rag_backend,  # type: ignore[arg-type]
        )
    )
    abstain_total = len(abstain_rows)
    recall_total = len(recall_rows)
    recall_pass = passed - abstain_pass if abstain_pass <= passed else 0

    print(f"{'Category':<12} {'Pass':>5} {'Total':>6} {'Rate':>7}")
    print("-" * 35)
    print(f"{'Abstain':<12} {abstain_pass:>5} {abstain_total:>6} {abstain_pass/abstain_total:.1%}" if abstain_total else "Abstain: no rows")
    print(f"{'Recall':<12} {recall_pass:>5} {recall_total:>6} {recall_pass/recall_total:.1%}" if recall_total else "Recall: no rows")
    print("-" * 35)
    print(f"\nTotal: {total}  Passed: {passed}  Failed: {len(failures)}")
    print(f"Overall accuracy: {accuracy:.2%}")

    if args.show_failures and failures:
        print(f"\nFailures ({len(failures)}):")
        for q, kind, reason in failures:
            print(f"  [{kind}] {reason!r}  — \"{q}\"")

    if args.exit_nonzero and accuracy < args.min_accuracy:
        print(
            f"\nFAIL: accuracy {accuracy:.2%} < required {args.min_accuracy:.2%}",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
