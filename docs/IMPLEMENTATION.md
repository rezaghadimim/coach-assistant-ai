# Implementation Plan Status

## Completed

### Phase 1: Core Chat
- FastAPI app and health endpoint
- `POST /api/chat`
- Ollama integration
- Phase 1 tests

### Phase 2: RAG Pipeline — Knowledge Retrieval
> RAG is for **what the model knows**. Store documents, books, articles, and any content that may change or grow here — not in the model weights.
- Document chunking and ingestion utilities (`.txt`, `.md`, `.pdf`)
- In-memory token-similarity retrieval index
- `POST /api/ingest` endpoint to reindex the knowledge base
- Chat prompt grounding: top-k retrieved chunks injected into the system prompt
- Phase 2 tests

### Phase 3: Memory System (Backend)
- SQLite schema + persistence layer
- User/session/message CRUD
- Session rollover + summary generation
- `POST /api/users`, `GET /api/users/{user_id}`
- `GET /api/sessions/{user_id}`, `POST /api/sessions/{user_id}/new`
- Phase 3 tests

### Phase 4: Web UI — Open WebUI Integration
- OpenAI-compatible API layer (`GET /v1/models`, `POST /v1/chat/completions`)
- Streaming response support via SSE
- Per-user session routing through `user` field or `X-User-Id` header
- `Dockerfile` and `docker-compose.yml` for running the full stack
- Phase 4 tests

### Client Management Tools (Chat)
- Ollama tool-calling loop in `app/core/llm.py`
- Client-management tools in `app/core/tools.py`
- Wired into `/api/chat` and `/v1/chat/completions`
- Profile merge on partial `create_client` updates
- Tests in `tests/test_tools.py`

### Client Notes API
- SQLite `client_notes` table (stories, decisions, goals, progress)
- CRUD endpoints under `/api/clients/{user_id}/notes`
- Notes auto-injected into the chat system prompt
- Tests in `tests/test_client_notes.py`

### Coaching Scope Guardrails
- Deterministic off-topic detection in `app/core/scope.py`
- Open WebUI task prompts (follow-ups, title, tags) allowed through
- Tests in `tests/test_scope.py`

### Client Intent Detection
- Regex-based fast path for common client-management commands in `app/core/client_intents.py`
- Write confirmation flow via `app/core/confirmations.py`
- Intent knowledge base in `app/core/intent_kb.py`
- Tests in `tests/test_client_intents.py` and `tests/test_intent_kb.py`

### Optional OpenRouter Provider
- Cloud LLM routing when `OPENROUTER_API_KEY` is set
- Provider abstraction in `app/core/llm_providers/`
- Dynamic model registry and availability probe
- Tests in `tests/test_openrouter.py`
- See [`OPENROUTER.md`](OPENROUTER.md)

### Phase 5 Prep: Training Data Export
- `scripts/export_training_data.py` — export closed sessions from SQLite to JSONL
- Export logic in `app/memory/training_export.py`
- Tests in `tests/test_training_export.py`

### Phase 2C: RAG Reranker — Two-Stage Retrieval (local cross-encoder)

**Problem solved:** single-pass bi-encoder retrieval with `top_k=3` had no opportunity to re-score candidates; a query that was semantically close to several chunks had no second-pass signal to surface the most relevant one.

**Done:**
- [x] Two-stage `retrieve()`: stage-1 fetches `RAG_RETRIEVE_K=30` candidates (hybrid RRF optional); stage-2 local cross-encoder narrows to `RAG_TOP_K=2`
- [x] `app/core/rerank.py` — fastembed ONNX cross-encoder (default `BAAI/bge-reranker-base`)
- [x] `app/rag/reranker.py` — thin wrapper, batch scoring, passage truncation, graceful fallback when fastembed is unavailable
- [x] Per-source deduplication: only the highest-scoring chunk per source file is kept
- [x] Configuration: `RAG_RETRIEVE_K`, `RAG_RERANK_ENABLED`, `RAG_RERANK_MODEL`, `RAG_RERANK_BATCH_SIZE`, `RAG_RERANK_MAX_PASSAGE_CHARS`, `RAG_RERANK_CACHE_DIR`
- [x] Startup logging + `/health` `rerank: {enabled, model, backend, available}`
- [x] Tests: `tests/test_rag_rerank.py`, `tests/test_rerank.py` (mocked — CI-safe), `tests/test_rerank_integration.py` (real model, optional)
- [x] Docs: `RAG.md`, `ARCHITECTURE.md`, ADR-0008

**To operate:**
```bash
pip install -r requirements.txt   # includes fastembed
RAG_RERANK_ENABLED=true python3 main.py
# first run downloads BAAI/bge-reranker-base to data/rerank_cache/
# startup log: rag: rerank ready | model=BAAI/bge-reranker-base (local cross-encoder via fastembed)
# per-request log: rag rerank | backend=fastembed model=... candidates=N final=M top_scores=[...]
```

See [`RAG.md`](RAG.md) for full configuration reference and [ADR-0008](adr/0008-cross-encoder-rag-reranker.md) for the rationale.

### Phase 2E: Per-Collection Video Knowledge — Multi-Expert RAG

**Problem solved:** coaches need answers grounded in **multiple experts' video guides**, with attributed citations (person, guide, timestamp), while framework docs stay on fast local embeddings.

**Done:**
- [x] Dual in-memory indices: `framework_index` + `collection_index` (`app/rag/retriever.py`)
- [x] Pluggable embed providers: Ollama, OpenRouter, OpenAI (`app/core/embed_providers/`)
- [x] Collection SQLite + filesystem layout (`app/knowledge/store.py`, `data/knowledge/collections/`)
- [x] SRT/VTT transcript parsing and time-aware chunking (`app/rag/transcript.py`)
- [x] Two-phase coach retrieval: situation alignment + expert solution expansion with `diversify_by_collection()`
- [x] Collections API: `GET/POST /api/collections`, sources, reindex, `process-jobs`
- [x] Media jobs: ffmpeg + faster-whisper (local), yt-dlp (YouTube) — optional host dependencies
- [x] Tests: `test_transcript_parser.py`, `test_collection_ingest.py`, `test_two_phase_retrieval.py`, `test_embed_providers.py`, `test_knowledge_jobs.py`
- [x] Docs: `RAG.md`, `ARCHITECTURE.md`, `knowledge/README.md`, ADR-0011

**To operate:**
```bash
# Optional: cloud embed for collections
export OPENROUTER_API_KEY=sk-or-v1-...

# Add collection files under data/knowledge/collections/{slug}/...
curl -X POST http://localhost:8000/api/ingest -H "Content-Type: application/json" -d '{}'

# Optional media pipeline (requires ffmpeg, yt-dlp, pip install faster-whisper)
curl -X POST http://localhost:8000/api/collections/process-jobs
```

See [`RAG.md`](RAG.md) and [ADR-0011](adr/0011-collection-video-knowledge.md).

### Phase 2D: Response Formatter — Human-Friendly Data Replies

**Problem solved:** fast-path data replies were accurate but mechanical ("Here are the details on file:\n\nClient ID: ali\n..."). A coach asking "what is Ali's email?" received a full profile block. The small-model risk of letting the LLM decide *what* to fetch was eliminated by keeping routing and tool execution deterministic and adding an optional LLM pass only for *presentation*.

**Done:**
- [x] Formatter module: `app/core/response_formatter.py` — `format_data_reply()`, `is_formattable()`, PII validation (`_EMAIL_RE`, `_PHONE_RE`), deterministic fallback
- [x] Config flag: `RESPONSE_FORMATTER_ENABLED` (default `true`) in `app/core/config.py`
- [x] Formatter wired into `app/core/llm.py` — applied after `try_direct_reply` and `_try_llm_router_action` fast-path returns
- [x] Formatter wired into `app/api/chat.py` — applied on the `try_direct_reply` early-return path
- [x] Tests: `tests/test_response_formatter.py` — 19 tests covering `is_formattable`, `format_data_reply`, PII drop fallback, LLM error fallback, flag integration
- [x] Benchmark: `scripts/benchmark_response_formatter.py` — 8-sample built-in eval set, latency OFF/ON, PII preservation, char delta
- [x] Docs: `ARCHITECTURE.md` (component 12, data flow step 6f, file map), `TOOL_ROUTING.md` (Response Formatting section), ADR-0010

**To operate:**
```bash
# Enabled by default — LLM-rephrased data replies (see ADR-0010 §6):
RESPONSE_FORMATTER_ENABLED=true

# Disable to skip the extra LLM call and use the deterministic template:
RESPONSE_FORMATTER_ENABLED=false

# Re-benchmark after changing model or hardware:
python3 scripts/benchmark_response_formatter.py --samples 8
# Target: PII preservation 100%; overhead typically 500-2000 ms per reply (~686 ms on llama3.1:8b).
```

See [ADR-0010](adr/0010-llm-response-formatter.md) for the rationale and design constraints.

### Phase 2B: Tool Routing — Embedding + Rerank + LLM Fallback

**Problem solved:** arbitrary phrasing ("give me all visitors in table", "dump the roster") was failing the fast path entirely, reaching the LLM but getting back follow-up suggestions instead of data — because all fast-path layers were lexical and couldn't handle out-of-vocabulary synonyms. Messages like "Ali's age is 23" were also misrouted to `add_client_note` instead of `create_client`.

**Done:**
- [x] Tool knowledge corpus: `docs/tool-knowledge/` (9 per-tool markdown docs + `examples/routing.jsonl`, now 307 examples)
- [x] Configuration: `TOOL_ROUTER_BACKEND`, `RAG_EMBED_MODEL`, `TOOL_ROUTER_THRESHOLD`, etc.
- [x] Embedding client: `app/core/embeddings.py` — Ollama `/api/embeddings` with E5 prefix support
- [x] Domain synonym lexicon: `app/core/lexicon.py` — `normalize_for_routing()` additive query expansion (`visitor→client`, `table→list clients`, `dump→show/list`, etc.); applied in token backend, embedding, and `top_n_tools`; never touches RAG
- [x] Tool router v2: `app/core/tool_router.py` — three backends (token, embedding, two-stage rerank), `ToolMatch.rerank_score` field, graceful degradation chain
- [x] Two-stage rerank: stage-1 embedding top-K recall (floor=0.30) → stage-2 fastembed cross-encoder precision (threshold=0.55); reuses `BAAI/bge-reranker-base` and `rag_rerank_cache_dir` from RAG
- [x] New config: `TOOL_ROUTER_RERANK_ENABLED`, `TOOL_ROUTER_RERANK_TOP_K`, `TOOL_ROUTER_EMBED_FLOOR`, `TOOL_ROUTER_RERANK_THRESHOLD`, `TOOL_ROUTER_RERANK_MARGIN`, `TOOL_ROUTER_RERANK_MODEL`, `TOOL_ROUTER_LLM_FALLBACK_ENABLED`
- [x] LLM router fallback: `app/core/llm_router.py` — one constrained LLM call returning `{"tool": "<name>"}` JSON; fired only when the message is a data request and all fast-path layers deferred
- [x] Dead-end fix: `_format_follow_ups_as_text` suppresses follow-up-only responses for data requests; `_empty_reply_fallback` attempts a direct-action rescue first
- [x] System prompt hardening: explicit `CRITICAL RULE` block in `COACH_ASSISTANT_SYSTEM_PROMPT` biasing tool calls for data retrieval; synonym phrasings added to all tool examples
- [x] Eval datasets: `data/eval/tool_routing.jsonl` (55 in-distribution rows), `data/eval/tool_routing_hard.jsonl` (71 out-of-vocab held-out rows)
- [x] Eval script: `scripts/eval_tool_routing.py` — `--backend rerank`, `--hard`, `--latency` flags added
- [x] Benchmark script: `scripts/benchmark_tool_routing.py` — compares token/embedding/rerank across standard + hard sets with accuracy, deferral rate, p50/p95 latency
- [x] API: `POST /api/tools/classify` (now exposes `rerank_score` field), `POST /api/tools/reindex`
- [x] Tests: `test_lexicon.py` (24), `test_tool_router_rerank.py` (12), `test_llm_router.py` (18), extended `test_tool_router.py` (6 out-of-vocab), extended `test_tools_api.py` (data-request guard + schema fields)

**To operate:**
```bash
# Minimal (token + lexicon, CI-safe)
python scripts/eval_tool_routing.py --backend token --show-errors

# With embedding + rerank (best accuracy)
ollama pull karuniaperjuangan/multilingual-e5-small
pip install fastembed
python scripts/eval_tool_routing.py --backend rerank --show-errors
python scripts/eval_tool_routing.py --backend rerank --hard --show-errors

# Full benchmark comparing all backends
python scripts/benchmark_tool_routing.py
```

See [`TOOL_ROUTING.md`](TOOL_ROUTING.md) for full guide.

### Anti-Hallucination Guardrails — Deterministic Data Integrity

**Problem solved:** the small local model (`llama3.1:8b`) sometimes reaches the
free-form tool-calling loop on a data-shaped question and *invents* client data
(a fabricated email/phone, or facts about a client who isn't even on file) rather
than calling a tool or abstaining. The LLM router was already hardened to 0%
hallucination, but the loop fallback had no such backstop. These guards are
fully deterministic — no extra LLM call — so they cannot themselves hallucinate.

**Done (2026-06-25):**
- [x] **A — PII fabrication guard.** `_ground_data_reply()` in `app/core/llm.py`:
  for a data request about a client on file, any email/phone in the reply that is
  **absent from that client's stored record** is treated as fabricated; the
  untrusted free-form text is replaced with the client's real record. Reuses the
  formatter's canonical `_pii_preserved()` check for consistent behavior. Wired
  into both text-return paths of the tool loop.
- [x] **B — grounding over free-form.** The same guard substitutes the truthful
  stored record whenever the loop's text answer fails PII grounding, so the coach
  receives real data instead of a plausible-but-wrong answer.
- [x] **C — entity short-circuit.** `_references_unknown_client()`: when a
  lookup names a client who is **not** on file, abstain deterministically
  (`I don't have a client named "X" on file…`) **before** any LLM call can invent
  a record. Fires inside the `_is_data_request` gate, before the LLM router.
- [x] **D — broadened `_is_data_request`.** See the Tool Routing → Medium impact
  entry below.
- [x] Tests: `tests/test_llm_guardrails.py` (12 tests, CI-safe — no Ollama):
  `_is_data_request` recall/exclusion, `_references_unknown_client` known vs.
  unknown, `_ground_data_reply` fabricated-PII replacement + legitimate-reply
  pass-through.

**Residual gap (documented, not fixed):** non-PII fabrication (e.g. inventing a
*goal* or *story* text) on a question that `_is_data_request` misses is not
caught by a regex guard. The mitigations are the hardened LLM router, the
object-noun-gated `_is_data_request`, and growing the corpus from production
logs — not a deterministic content check.

## Remaining

### Response Formatter — Next Steps

- [x] **Run the benchmark and baseline latency overhead.** Baseline on `llama3.1:8b` (2026-06-20): PII 100%, avg overhead 686 ms, avg char delta −106. Re-run after model or hardware changes:
  ```bash
  python scripts/benchmark_response_formatter.py
  ```
  Target: PII preservation 100%; latency overhead < 2000 ms per reply.

- [x] **Tune or replace the formatter system prompt** if the model produces poor rephrasing. Inspect outputs with `RESPONSE_FORMATTER_ENABLED=true` and one test message. If the model ignores the "answer only what was asked" rule, add a few-shot example to the prompt.

- [x] **Add per-tool formatter hints** for special cases (e.g. a multi-client list → compact table, or a notes list → numbered list). Wire them through `format_data_reply()` as an optional `hint` argument.

- [x] **Extend `_PHONE_RE`** to cover regional formats used by the coach's clients.

---

### Tool Routing — Next Steps for Better Coverage

The current stack (lexicon → token → embedding → rerank → LLM fallback) handles the most common routing failures. The following steps would push coverage further.

#### High impact (do first)

- [x] **Run the benchmark and measure the baseline.** Baseline on this hardware
  (2026-06-25, corpus = 307 examples, `llama3.1:8b` + `multilingual-e5-small` +
  `BAAI/bge-reranker-base`):

  | Backend   | Standard (55) acc / defer | Hard (71) acc / defer | Precision |
  |-----------|---------------------------|------------------------|-----------|
  | token     | 96.4% / 0.0%              | 97.2% / 2.8%           | —         |
  | embedding | 96.4% / 0.0%              | 97.2% / 2.8%           | —         |
  | rerank    | 96.4% / 0.0%              | 97.2% / 2.8%           | **1.00 on every tool** |

  The three backends are near-identical on these sets because the corpus grew to
  307 and `TOOL_ROUTER_THRESHOLD` was already tuned to 0.65 — the standard/hard
  sets no longer separate them. The rerank layer's distinct value is on truly
  out-of-vocabulary production phrasings, which these held-out sets only
  partially capture. **rerank precision is 1.00 on every tool on both sets — it
  never fires a wrong tool; every failure is a (safe) deferral.** Re-run:
  ```bash
  python scripts/benchmark_tool_routing.py
  python scripts/eval_tool_routing.py --backend rerank --hard --show-errors
  ```
  (Note: Ollama can drop connections under the benchmark's concurrent load —
  if the rerank column shows a spike in deferrals + a sub-10 ms p50, that's the
  embed stage failing, not real behavior. Re-run rerank in isolation via
  `eval_tool_routing.py`.)

- [ ] **Grow `examples/routing.jsonl` with real failure cases.** Add every
  message that was misrouted or deferred **in production**. Use
  `POST /api/tools/classify` to inspect scores without restarting.
  ```bash
  curl -X POST http://localhost:8000/api/tools/classify \
    -H "Content-Type: application/json" \
    -d '{"message": "your failing message here"}'
  ```
  ⚠️ **Do not copy hard-eval failures into the corpus** — `tool_routing_hard.jsonl`
  is a held-out set; training on it destroys its value as a generalization
  measure. Production logs only.

- [x] **Tune `TOOL_ROUTER_RERANK_THRESHOLD`.** Swept 0.45 / 0.50 / 0.55 on the
  hard set (2026-06-25): **identical results at every value** — keep the 0.55
  default. The two hard-set deferrals are not threshold-limited:
  - `"Dump the database"` — best cross-encoder score is **0.006** (the reranker
    doesn't connect the abstract phrasing to any candidate); no sane threshold
    recovers it. It defers to the LLM router (`_is_data_request` = True), which
    handles it.
  - `"what notes do we have on Sara"` — best score **1.000** (`list_client_notes`)
    but runner-up `get_client_full` ("What do we have on Sara?") is **0.999** →
    margin 0.001 ≪ `TOOL_ROUTER_RERANK_MARGIN` (0.10). A genuine margin tie, not
    a threshold miss. Lowering the *threshold* cannot recover it; the margin
    guard correctly abstains on an ambiguous pair.

  Since rerank precision is already 1.00, lowering the threshold only admits
  more false positives for zero recall gain. The right levers for these two are
  the corpus (production examples) and `_is_data_request` coverage — not the
  threshold.

- [ ] **Extend `lexicon.py` from production logs.** The current lexicon is hand-crafted. After running in production for a week, grep the logs for messages that were deferred (`_embed_available` probe OK but `classify_tool` returned None) and add any recurring synonym groups.

#### Medium impact

- [x] **Improve the `_is_data_request` pattern (guardrail D).** Broadened the
    trigger-verb group (2026-06-25) to add contraction forms (`who's`, `what's`,
    `where's`), `do (i|we|you) have`, and `look up`, while keeping the
    object-noun gate that prevents coaching-question false positives. Verified:
    `"what's Sara's email"`, `"do we have any notes on Sara"`,
    `"look up the phone for Reza"` now route to the data path; `"how can I help a
    client feel stuck"` and `"what progress should Sara aim for"` stay False.
  - **Residual (acceptable):** `"what notes do we have on Sara"` still returns
    False because the object noun (`notes`) precedes the verb (`do we have`), and
    matching inverted order would risk false positives. Low-frequency; this exact
    phrase is also the rerank margin-tie case (see threshold note above), so it
    defers safely. Revisit only if production logs show recurring inverted-order
    misses.

- [x] **Add an observability endpoint for near-misses.** When `classify_tool` returns None, log the top-3 scores so you can see whether the correct tool was close but below threshold. Wired into `/health` via `tool_router` stats and structured `tool_router.deferral` logs.

- [x] **Test LLM router fallback accuracy.** Built a labeled eval set
  (`data/eval/llm_router.jsonl`, 41 rows) — the first to include `"none"` rows,
  i.e. *data-shaped coaching questions* that trip `_is_data_request` and so
  actually reach the router. New eval `scripts/eval_llm_router.py` reports a
  **hallucination rate**: how often a coaching question is wrongly assigned a
  tool (the router executes read tools directly, so a wrong pick = a fabricated
  data answer). Baseline on `llama3.1:8b` was **78.0% accuracy, 46.7%
  hallucination** (`none` recall 0.53). Hardening `_SYSTEM_PROMPT` with a sharp
  "specific stored record vs. general advice" rule + data-shaped `none`
  exemplars raised it to **95.1% accuracy, 0% hallucination** (`none` recall
  1.00), with no regression in data-request recall. Guarded by
  `tests/test_eval_llm_router.py` (CI-safe: dataset integrity + trap coverage)
  and `tests/test_llm_router_integration.py` (optional live regression: accuracy
  ≥ 0.90, hallucination ≤ 0.10; skips without Ollama).
  ```bash
  PYTHONPATH=. python scripts/eval_llm_router.py --show-errors
  ```

#### Lower impact / future

- [ ] **Explore a learned threshold.** Rather than a global `TOOL_ROUTER_RERANK_THRESHOLD`, train a simple logistic regression on the hard eval set to learn per-tool or score-distribution-aware thresholds. Requires a larger labeled dataset.

- [ ] **Export routing failures to fine-tuning data.** Any message where the LLM router or tool loop correctly identified the tool (but the fast path deferred) is a candidate training example for further `routing.jsonl` expansion or a future fine-tuned router model.

---

### Phase 5: Fine-tuning (LoRA) — Behavior Adaptation
> Fine-tuning is for **how the model behaves**, not what it knows. Use this to teach the model the coach's tone, questioning style, and response patterns — not to inject knowledge that belongs in RAG.

**Done (tooling):**
- [x] Export script: `python scripts/export_training_data.py --output training_data.jsonl`

**Still to do (data + training):**
- [ ] Collect 500+ real coaching conversations (behavior examples, not documents)
- [ ] Validate that RAG + prompting isn't sufficient for your quality bar
- [ ] Train a LoRA adapter on coaching style, tone, and questioning strategy
- [ ] Evaluate adapter quality against the coaching methodology
- [ ] Deploy fine-tuned model in Ollama and point `ollama_model` at it

See [`FINETUNE.md`](FINETUNE.md) for the full guide, export options, and decision rules.

## Test Command

```bash
python3 -m pytest tests/
```
