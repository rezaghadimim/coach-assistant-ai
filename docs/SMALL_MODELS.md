# Small-Model Guide — running Coach Assistant AI on minimal hardware

This project is deliberately architected so that **most correctness does not
depend on the LLM**. Deterministic layers (intent detection, tool router,
guardrails A/B/C/E) run before and after every model call, so swapping in a
smaller model degrades *style*, not *truth*. This guide explains which model
does what, how to go smaller safely, and how to validate a swap.

## 1. The model inventory

| Role | Current default | Size | Where configured |
|------|-----------------|------|------------------|
| Chat / tool-calling LLM | `llama3.1:8b` (Ollama) | ~4.9 GB | `OLLAMA_MODEL` |
| Embeddings (RAG + tool router) | `karuniaperjuangan/multilingual-e5-small` | ~120 MB, 384-dim | `OLLAMA_EMBED_MODEL`, `RAG_EMBED_MODEL` |
| Cross-encoder reranker | `BAAI/bge-reranker-base` (fastembed/ONNX, in-process) | ~1 GB | `RAG_RERANK_MODEL`, `TOOL_ROUTER_RERANK_MODEL` |

**Embeddings and reranker are already at the practical minimum.** E5-small is
the smallest good multilingual embedder; `bge-reranker-base` is the smallest
multilingual cross-encoder fastembed ships (the smaller MiniLM/Jina rerankers
are English-only — do not switch to them while the corpus and coaches use
Persian/multilingual text). The place to save memory is the chat LLM.

## 2. What the chat LLM actually has to do

Per message, in order of difficulty:

1. **Classify** (LLM router): emit `{"tool": "..."}` — constrained by an Ollama
   `format=` JSON schema, temperature 0, 64-token budget. Even 1–3B models do
   this reliably because the schema makes invalid output impossible.
2. **Rephrase** (response formatter): rewrite a deterministic data template in
   natural language — validated afterwards by the PII-preservation check, which
   falls back to the template on any error. Low risk.
3. **Tool-calling loop**: pick tools and construct arguments. This is where
   small models differ most — the model must support Ollama tool calling.
4. **Free-form coaching advice**: quality is subjective; grounding is enforced
   by the RAG prompt + guardrails.

Because 1–2 are schema/validation-protected and 3–4 are guarded, a 3–4B model
is a realistic target.

### Recommended candidates (in order)

| Model | Why |
|-------|-----|
| `qwen3:4b` | Best small tool-caller in Ollama; strong multilingual (incl. Persian) |
| `qwen2.5:3b-instruct` | Slightly smaller, still solid tool calling + multilingual |
| `llama3.2:3b` | Fine for advice; weaker at structured tool calls — expect more rescue-path hits |

Avoid models without Ollama tool support (e.g. `gemma3` family) — the agentic
loop in `app/core/llm.py` needs native `tools=` handling.

## 3. How to swap and validate — the checklist

Never judge a model swap by chatting with it. Run the evaluation harnesses:

```bash
# 0. Smoke-benchmark the whole pipeline first (see docs/BENCHMARKS.md)
.venv/bin/python scripts/benchmark_pipeline.py

# 1. Pull and point the app at the new model
ollama pull qwen3:4b
# .env: OLLAMA_MODEL=qwen3:4b

# 2. LLM router classification accuracy (structured JSON at temp=0)
.venv/bin/python scripts/eval_llm_router.py

# 3. End-to-end tool routing accuracy (307-example corpus)
.venv/bin/python scripts/eval_tool_routing.py

# 4. Response formatter: PII preservation + latency
#    (the "PII 100%" benchmark was measured on llama3.1:8b — re-verify!)
.venv/bin/python scripts/benchmark_formatter_hints.py

# 5. RAG grounding / abstention behavior
.venv/bin/python scripts/eval_rag_grounding.py

# 6. Unit suite (offline, ~3s)
RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false \
  .venv/bin/python -m pytest -q tests/ --ignore=tests/test_eval_llm_router.py
```

Acceptance bar for a swap:

- LLM router accuracy within ~3 points of the 8B baseline (the deterministic
  router catches most traffic first, so small regressions here matter little).
- Formatter PII preservation at 100% — anything less, set
  `RESPONSE_FORMATTER_ENABLED=false` (the deterministic template is always
  correct) rather than accepting leakage.
- Watch the step logs for `reason=malformed_tool_call` and `fallback` rates:
  a small model that frequently emits broken tool calls will still *answer
  correctly* via the rescue paths, but each rescue costs an extra LLM call.

## 4. Context and memory settings that matter more than model choice

- **`OLLAMA_NUM_CTX` (default 8192).** The single most common "small model is
  hallucinating" cause is actually prompt truncation: Ollama's own default
  (2048–4096) drops the *top* of the prompt — the system prompt and tool
  definitions — once RAG chunks + client notes are injected. If you shrink the
  model to save RAM, do **not** shrink `num_ctx` below ~6k without also
  reducing injected context (`RAG_PROBLEM_TOP_K`, `RAG_EXPERT_TOP_K`, the
  10-note client-documentation cap in `app/api/chat.py`).
- **`OLLAMA_KEEP_ALIVE` (default 30m).** Keeps the chat model resident so the
  first message after a pause doesn't pay a full reload. Set `-1` on a
  dedicated machine. Note the embed model and chat model both live in Ollama —
  with very tight RAM they can evict each other; a smaller chat model helps
  both stay loaded.
- KV-cache RAM scales with `num_ctx` × model size: a 4B model at 8192 ctx uses
  far less than an 8B at the same window — another reason the 3–4B tier is the
  sweet spot.

## 5. Latency knobs (CPU reranking is the hidden cost)

Each non-direct message runs up to two cross-encoder passes (problem phase ≤20
candidates, expert phase ≤30) plus one for the tool router (≤10). On CPU this
usually dominates end-to-end latency, not the LLM. If responses feel slow:

1. `RAG_RERANK_MAX_PASSAGE_CHARS=2000 → 1200` — roughly halves per-passage
   scoring cost with little quality loss (E5 chunks are ~300 words anyway).
2. `RAG_RETRIEVE_K=30 → 15` — fewer candidates scored per phase.
3. `RAG_RERANK_BATCH_SIZE` — throughput-neutral on most CPUs; leave at 32.
4. Only as a last resort: `RAG_RERANK_ENABLED=false`. Retrieval then returns
   stage-1 hybrid results with their real similarity scores (safe since the
   2026-07 fix), but you lose the 0.42 abstention floor that suppresses
   off-topic chunks — expect slightly noisier grounding.

## 6. Invariants — do not break these when iterating

These are the load-bearing design decisions; future changes should preserve them:

1. **Scores must stay comparable to their floor.** Stage-1 cosine scores are
   filtered by `RAG_MIN_SCORE`; cross-encoder sigmoid scores by
   `RAG_RERANK_MIN_SCORE`. RRF fused scores (~0.03) are for ordering only and
   must never reach either filter. If you add a new fusion/scoring stage, decide
   explicitly which floor its scores are compared against.
2. **Rerank failure must be loud to the caller.** `app/rag/reranker.rerank`
   raises on scoring failure; `_retrieve_from_indices` catches and falls back
   to stage-1 scores. Don't "helpfully" swallow exceptions inside the reranker —
   that reintroduces the silent-empty-retrieval bug.
3. **The LLM never sees ungated writes.** Write tools stop the loop at ⏳/✅/❌
   and the confirmation flow is deterministic.
4. **PII validation runs after every LLM rephrase**, and the deterministic
   template is always the fallback. New formatter features must keep this order.
5. **Temperature 0 for anything classified or grounded** (`TEMPERATURE_TOOL`,
   `TEMPERATURE_GROUNDED`); only free-form advice uses `TEMPERATURE_ADVICE`.
6. **Both API endpoints pre-check the direct path** and call
   `generate_response(..., skip_direct_reply=True)`. A new endpoint must either
   pre-check like they do, or omit the flag and let the loop check — never
   neither.

## 7. If you outgrow this setup

- **Fully local, faster embeddings:** fastembed (already a dependency) can run
  E5-class embedders in-process with real batching — removes the Ollama HTTP
  round-trip per query. Implement as a new provider in
  `app/core/embed_providers/`.
- **Bigger corpora (>~5k chunks):** the in-memory cosine loop in
  `app/rag/retriever.py` is O(n) per query in pure Python. Move to numpy dot
  products first (fastembed already pulls numpy in); only reach for a vector DB
  (qdrant) after that stops being enough.
- **GPU appears:** revisit `RAG_RERANK_MODEL=BAAI/bge-reranker-v2-m3` (better
  multilingual quality; note `config.py` currently normalizes that name back to
  `bge-reranker-base` for the Ollama-legacy case — adjust the validator) and an
  8B+ chat model.
