"""Full-pipeline smoke benchmark — verify every layer works and meets its latency budget.

Runs each layer of the stack in-process (no running API needed) and reports
OK / WARN / FAIL / SKIP per check with latency. Designed for three uses:

    1. After changing anything (model swap, config, code):
           .venv/bin/python scripts/benchmark_pipeline.py
    2. Fast offline sanity (CI, no Ollama):
           .venv/bin/python scripts/benchmark_pipeline.py --offline
    3. Automation / cron (machine-readable, alert on exit code):
           .venv/bin/python scripts/benchmark_pipeline.py --json

Exit codes:  0 = all OK (warnings allowed unless --strict)
             1 = at least one FAIL (or WARN with --strict)

Checks (in order):
    config          — settings coherence (thresholds, pool sizes, num_ctx)
    ollama          — server reachable, chat + embed models pulled
    llm.complete    — one tiny chat completion
    embed.query     — one query embedding
    rerank.score    — cross-encoder loads and scores
    rag.index       — knowledge ingest + index non-empty
    rag.retrieve    — known-good query returns grounded chunks
    rag.abstain     — off-topic query returns nothing
    rag.fallback    — regression guard: broken reranker must NOT empty retrieval
    router.token    — deterministic tool router classifies canonical utterances
    router.llm      — constrained LLM classify returns a valid tool
    formatter.pii   — LLM-formatted data reply preserves email/phone verbatim

See docs/BENCHMARKS.md for budgets, guidelines, and alerting setup.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ---------------------------------------------------------------------------
# Latency budgets (milliseconds). Generous for CPU-only machines; a WARN means
# "worked, but slower than expected — look into it", not "broken".
# ---------------------------------------------------------------------------
BUDGETS_MS = {
    "ollama": 1_000,
    "llm.complete": 15_000,
    "embed.query": 2_000,
    "rerank.score": 5_000,
    "rag.index": 60_000,
    "rag.retrieve": 8_000,
    "rag.abstain": 2_000,
    "rag.fallback": 8_000,
    # Up to 3 classify calls, each doing embed + cross-encoder rerank when the
    # embedding backend is active (vs. a single free token-cosine call offline).
    "router.token": 3_000,
    "router.llm": 15_000,
    "formatter.pii": 15_000,
}

OK, WARN, FAIL, SKIP = "OK", "WARN", "FAIL", "SKIP"
_STATUS_ICON = {OK: "✅", WARN: "⚠️ ", FAIL: "❌", SKIP: "⏭️ "}


@dataclass
class Result:
    name: str
    status: str
    ms: int = 0
    detail: str = ""


@dataclass
class Context:
    """State shared between checks so later checks can skip early failures."""

    offline: bool = False
    ollama_up: bool = False
    chat_model_ok: bool = False
    embed_model_ok: bool = False
    index_chunks: int = 0
    results: list[Result] = field(default_factory=list)


def _run(name: str, fn, ctx: Context) -> Result:
    t0 = time.monotonic()
    try:
        status, detail = fn(ctx)
    except Exception as exc:  # noqa: BLE001 — every failure must be reported, not raised
        status, detail = FAIL, f"{type(exc).__name__}: {exc}"
    ms = int((time.monotonic() - t0) * 1000)
    budget = BUDGETS_MS.get(name)
    if status == OK and budget is not None and ms > budget:
        status, detail = WARN, f"{detail + ' — ' if detail else ''}{ms}ms exceeds {budget}ms budget"
    result = Result(name=name, status=status, ms=ms, detail=detail)
    ctx.results.append(result)
    return result


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_config(ctx: Context) -> tuple[str, str]:
    from app.core.config import settings

    problems: list[str] = []
    if settings.rag_retrieve_k < settings.rag_top_k:
        problems.append("RAG_RETRIEVE_K < RAG_TOP_K")
    if settings.rag_rerank_min_score <= settings.rag_min_score:
        problems.append("RAG_RERANK_MIN_SCORE must exceed RAG_MIN_SCORE")
    if not (0.0 < settings.rag_rerank_min_score < 1.0):
        problems.append("RAG_RERANK_MIN_SCORE outside (0,1) — reranker emits sigmoid scores")
    if settings.rag_chunk_size > 300 and "e5" in settings.rag_embed_model.lower():
        problems.append(f"RAG_CHUNK_SIZE={settings.rag_chunk_size} > 300 truncates E5 embeddings")
    if settings.ollama_num_ctx < 4096:
        problems.append(f"OLLAMA_NUM_CTX={settings.ollama_num_ctx} < 4096 risks prompt truncation")
    if settings.temperature_tool != 0.0:
        problems.append("TEMPERATURE_TOOL should be 0.0 for deterministic tool calls")
    if problems:
        return FAIL, "; ".join(problems)
    return OK, f"model={settings.ollama_model} num_ctx={settings.ollama_num_ctx}"


def check_ollama(ctx: Context) -> tuple[str, str]:
    if ctx.offline:
        return SKIP, "--offline"
    import httpx

    from app.core.config import settings

    with httpx.Client(base_url=settings.ollama_base_url, timeout=5.0) as client:
        version = client.get("/api/version").json().get("version", "?")
        tags = client.get("/api/tags").json().get("models", [])
    ctx.ollama_up = True
    names = {model.get("name", "").split(":latest")[0] for model in tags}
    missing = []
    chat_model = settings.ollama_model
    embed_model = settings.ollama_embed_model
    ctx.chat_model_ok = any(chat_model in name or name in chat_model for name in names)
    ctx.embed_model_ok = any(embed_model in name or name in embed_model for name in names)
    if not ctx.chat_model_ok:
        missing.append(f"chat model '{chat_model}' not pulled")
    if not ctx.embed_model_ok:
        missing.append(f"embed model '{embed_model}' not pulled")
    if missing:
        return FAIL, f"v{version}; " + "; ".join(missing) + " — run `ollama pull <model>`"
    return OK, f"v{version}, {len(tags)} models, chat+embed present"


def check_llm_complete(ctx: Context) -> tuple[str, str]:
    if ctx.offline or not ctx.chat_model_ok:
        return SKIP, "Ollama/chat model unavailable"
    from app.core.llm_providers.ollama import OllamaProvider

    result = asyncio.run(
        OllamaProvider().complete(
            [{"role": "user", "content": "Reply with exactly: pong"}],
            temperature=0.0,
            num_predict=8,
        )
    )
    if not result.content.strip():
        return FAIL, "empty completion"
    return OK, f"reply={result.content.strip()[:30]!r}"


def check_embed_query(ctx: Context) -> tuple[str, str]:
    if ctx.offline or not ctx.embed_model_ok:
        return SKIP, "Ollama/embed model unavailable"
    from app.core.embeddings import embed_query

    vector = embed_query("how do I structure a coaching session?")
    if not vector or len(vector) < 100:
        return FAIL, f"suspicious vector (dim={len(vector) if vector else 0})"
    return OK, f"dim={len(vector)}"


def check_rerank_score(ctx: Context) -> tuple[str, str]:
    from app.core.config import settings

    if not settings.rag_rerank_enabled:
        return SKIP, "RAG_RERANK_ENABLED=false"
    from app.core.rerank import fastembed_installed, rerank_documents

    if not fastembed_installed():
        return FAIL, "fastembed not installed but RAG_RERANK_ENABLED=true"
    scores = rerank_documents(
        "how to set client goals",
        ["setting goals with the GROW model", "recipe for chocolate cake"],
        batch_size=2,
    )
    if len(scores) != 2:
        return FAIL, f"expected 2 scores, got {len(scores)}"
    if not all(0.0 < score < 1.0 for score in scores):
        return FAIL, f"scores outside sigmoid range: {scores}"
    if scores[0] <= scores[1]:
        return WARN, f"relevant passage not ranked above off-topic one: {scores}"
    return OK, f"scores=({scores[0]:.2f}, {scores[1]:.2f})"


def check_rag_index(ctx: Context) -> tuple[str, str]:
    from app.core.config import settings

    if not settings.rag_enabled:
        return SKIP, "RAG_ENABLED=false"
    from app.core.knowledge_paths import knowledge_starter_dir

    if not knowledge_starter_dir().exists():
        return FAIL, f"starter dir missing: {settings.rag_knowledge_starter_dir}"

    from app.core.embeddings import probe_embed_model
    from app.rag.retriever import ingest_and_index_knowledge

    use_embed = not ctx.offline and settings.rag_backend in ("embedding", "auto") and probe_embed_model()
    docs, chunks = ingest_and_index_knowledge(
        chunk_size=settings.rag_chunk_size,
        chunk_overlap=settings.rag_chunk_overlap,
        embed=use_embed,
        cache_path=settings.rag_index_cache_path if use_embed else None,
        include_collections=True,
    )
    ctx.index_chunks = chunks
    if chunks == 0:
        return FAIL, "index is empty — nothing to retrieve from"
    return OK, f"docs={docs} chunks={chunks} backend={'embedding' if use_embed else 'token'}"


def check_rag_retrieve(ctx: Context) -> tuple[str, str]:
    if ctx.index_chunks == 0:
        return SKIP, "index empty"
    from app.core.config import settings
    from app.rag.retriever import retrieve_coach_context

    result = retrieve_coach_context("How do I run a GROW session with a client who feels stuck?")
    total = len(result.problem_chunks) + len(result.expert_chunks)
    if total == 0:
        return FAIL, (
            "known-good coaching query retrieved nothing — check embed backend, "
            f"RAG_MIN_SCORE={settings.rag_min_score}, RAG_RERANK_MIN_SCORE={settings.rag_rerank_min_score}"
        )
    top = result.problem_chunks[0] if result.problem_chunks else result.expert_chunks[0]
    return OK, f"problem={len(result.problem_chunks)} expert={len(result.expert_chunks)} top_score={top.score:.2f}"


def check_rag_abstain(ctx: Context) -> tuple[str, str]:
    if ctx.index_chunks == 0:
        return SKIP, "index empty"
    from app.rag.retriever import retrieve_coach_context

    result = retrieve_coach_context("how do I replace the timing belt on a 2014 Honda Civic?")
    total = len(result.problem_chunks) + len(result.expert_chunks)
    if total > 0:
        return WARN, f"off-topic query retrieved {total} chunks — grounding may be noisy"
    return OK, "off-topic query correctly retrieved nothing"


def check_rag_fallback(ctx: Context) -> tuple[str, str]:
    """Regression guard: a broken cross-encoder must degrade, not empty, retrieval."""
    if ctx.index_chunks == 0:
        return SKIP, "index empty"
    from app.core.config import settings

    if not settings.rag_rerank_enabled:
        return SKIP, "RAG_RERANK_ENABLED=false"
    import logging

    from app.rag.retriever import retrieve_coach_context

    # The simulated failure emits rag.rerank fail warnings — mute them so the
    # benchmark output doesn't look like a real incident.
    logging.disable(logging.WARNING)
    try:
        with patch(
            "app.rag.reranker.rerank_documents",
            side_effect=RuntimeError("simulated cross-encoder failure"),
        ):
            result = retrieve_coach_context(
                "How do I run a GROW session with a client who feels stuck?"
            )
    finally:
        logging.disable(logging.NOTSET)
    total = len(result.problem_chunks) + len(result.expert_chunks)
    if total == 0:
        return FAIL, "broken reranker emptied retrieval — stage-1 fallback is not working"
    return OK, f"fallback returned {total} chunks with reranker down"


def check_router_token(ctx: Context) -> tuple[str, str]:
    from app.core.config import settings

    if not settings.tool_router_enabled:
        return SKIP, "TOOL_ROUTER_ENABLED=false"
    import app.core.tool_router as tool_router

    count = tool_router.build_index()
    if count == 0:
        return FAIL, "routing.jsonl produced 0 examples"
    # Token backend only routes near-exact corpus matches (paraphrases defer to
    # the embedding/rerank/LLM layers by design), so require paraphrase routing
    # only when the embedding index is active.
    cases = {
        "who are my clients?": "list_clients",
        "show me all my clients": "list_clients",
    }
    embed_active = bool(tool_router._embed_available and len(tool_router._embed_backend))
    if embed_active:
        # Not "show me everything about Sara" — that phrase sits almost
        # exactly between get_client_full and list_client_notes in this
        # corpus (rerank margin <0.01), so classify_tool correctly defers
        # to the LLM router for it. Use an unambiguous paraphrase instead.
        cases["get Sara complete profile including notes"] = "get_client_full"
    misses = []
    for utterance, expected in cases.items():
        match = tool_router.classify_tool(utterance)
        got = match.tool if match else None
        if got != expected:
            misses.append(f"{utterance!r} → {got} (expected {expected})")
    if misses:
        return FAIL, "; ".join(misses)
    backend = "embedding+rerank" if embed_active else "token"
    return OK, f"{count} examples, {len(cases)}/{len(cases)} routed via {backend} backend"


def check_router_llm(ctx: Context) -> tuple[str, str]:
    from app.core.config import settings

    if ctx.offline or not ctx.chat_model_ok:
        return SKIP, "Ollama/chat model unavailable"
    if not settings.tool_router_llm_fallback_enabled:
        return SKIP, "TOOL_ROUTER_LLM_FALLBACK_ENABLED=false"
    from app.core.llm_router import classify_tool_llm

    match = asyncio.run(classify_tool_llm("who is in the database?"))
    if match is None:
        return FAIL, "constrained classify returned none for an obvious list_clients query"
    if match.tool != "list_clients":
        return WARN, f"classified as {match.tool} (expected list_clients)"
    return OK, f"tool={match.tool}"


def check_formatter_pii(ctx: Context) -> tuple[str, str]:
    from app.core.config import settings

    if ctx.offline or not ctx.chat_model_ok:
        return SKIP, "Ollama/chat model unavailable"
    if not settings.response_formatter_enabled:
        return SKIP, "RESPONSE_FORMATTER_ENABLED=false"
    from app.core.llm_providers.ollama import OllamaProvider
    from app.core.response_formatter import format_data_reply

    email, phone = "benchmark.client@example.com", "09121234567"
    raw = (
        "Here are the details on file:\n\n"
        f"Name: Benchmark Client\nAge: 41\nEmail: {email}\nPhone: {phone}\n"
        "Occupation: Analyst\nNo notes on file."
    )
    formatted = asyncio.run(
        format_data_reply(
            "get Benchmark Client's full profile", raw, OllamaProvider(), tool="get_client_full"
        )
    )
    if email not in formatted or phone not in formatted:
        return FAIL, "PII missing from formatted reply AND deterministic fallback did not fire"
    changed = "unchanged (deterministic fallback)" if formatted == raw else "rephrased"
    return OK, f"email+phone preserved verbatim ({changed})"


CHECKS = [
    ("config", check_config),
    ("ollama", check_ollama),
    ("llm.complete", check_llm_complete),
    ("embed.query", check_embed_query),
    ("rerank.score", check_rerank_score),
    ("rag.index", check_rag_index),
    ("rag.retrieve", check_rag_retrieve),
    ("rag.abstain", check_rag_abstain),
    ("rag.fallback", check_rag_fallback),
    ("router.token", check_router_token),
    ("router.llm", check_router_llm),
    ("formatter.pii", check_formatter_pii),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true",
                        help="skip checks that need Ollama (CI-safe)")
    parser.add_argument("--json", action="store_true",
                        help="emit one JSON object (for cron/monitoring)")
    parser.add_argument("--strict", action="store_true",
                        help="treat WARN as failure (exit 1)")
    parser.add_argument("--only", metavar="NAME",
                        help="run a single check by name (e.g. rag.fallback)")
    args = parser.parse_args()

    ctx = Context(offline=args.offline)
    checks = [(n, f) for n, f in CHECKS if not args.only or n == args.only]
    if not checks:
        print(f"unknown check {args.only!r}; valid: {', '.join(n for n, _ in CHECKS)}")
        return 1

    for name, fn in checks:
        result = _run(name, fn, ctx)
        if not args.json:
            print(f"{_STATUS_ICON[result.status]} {result.name:<16} {result.ms:>7}ms  {result.detail}")

    failed = [r for r in ctx.results if r.status == FAIL]
    warned = [r for r in ctx.results if r.status == WARN]
    ok = not failed and (not warned or not args.strict)

    if args.json:
        print(json.dumps({
            "status": "ok" if ok else "fail",
            "failed": [r.name for r in failed],
            "warned": [r.name for r in warned],
            "checks": [r.__dict__ for r in ctx.results],
        }))
    else:
        print()
        verdict = "ALL GOOD" if ok else "PROBLEMS FOUND"
        print(f"{'✅' if ok else '❌'} {verdict} — "
              f"{sum(r.status == OK for r in ctx.results)} ok, "
              f"{len(warned)} warn, {len(failed)} fail, "
              f"{sum(r.status == SKIP for r in ctx.results)} skipped")
        if failed or warned:
            print("   See docs/BENCHMARKS.md for what each check means and how to fix it.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
