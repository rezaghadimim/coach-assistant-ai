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
- [x] Tool knowledge corpus: `docs/tool-knowledge/` (9 per-tool markdown docs + `routing.jsonl`, now 130 examples)
- [x] Configuration: `TOOL_ROUTER_BACKEND`, `OLLAMA_EMBED_MODEL`, `TOOL_ROUTER_THRESHOLD`, etc.
- [x] Embedding client: `app/core/embeddings.py` — Ollama `/api/embeddings` with E5 prefix support
- [x] Domain synonym lexicon: `app/core/lexicon.py` — `normalize_for_routing()` additive query expansion (`visitor→client`, `table→list clients`, `dump→show/list`, etc.); applied in token backend, embedding, and `top_n_tools`; never touches RAG
- [x] Tool router v2: `app/core/tool_router.py` — three backends (token, embedding, two-stage rerank), `ToolMatch.rerank_score` field, graceful degradation chain
- [x] Two-stage rerank: stage-1 embedding top-K recall (floor=0.30) → stage-2 fastembed cross-encoder precision (threshold=0.55); reuses `BAAI/bge-reranker-base` and `rag_rerank_cache_dir` from RAG
- [x] New config: `TOOL_ROUTER_RERANK_ENABLED`, `TOOL_ROUTER_RERANK_TOP_K`, `TOOL_ROUTER_EMBED_FLOOR`, `TOOL_ROUTER_RERANK_THRESHOLD`, `TOOL_ROUTER_RERANK_MARGIN`, `TOOL_ROUTER_RERANK_MODEL`, `TOOL_ROUTER_LLM_FALLBACK_ENABLED`
- [x] LLM router fallback: `app/core/llm_router.py` — one constrained LLM call returning `{"tool": "<name>"}` JSON; fired only when the message is a data request and all fast-path layers deferred
- [x] Dead-end fix: `_format_follow_ups_as_text` suppresses follow-up-only responses for data requests; `_empty_reply_fallback` attempts a direct-action rescue first
- [x] System prompt hardening: explicit `CRITICAL RULE` block in `COACH_ASSISTANT_SYSTEM_PROMPT` biasing tool calls for data retrieval; synonym phrasings added to all tool examples
- [x] Eval datasets: `data/eval/tool_routing.jsonl` (59 in-distribution rows), `data/eval/tool_routing_hard.jsonl` (34 out-of-vocab held-out rows)
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

## Remaining

### Response Formatter — Next Steps

- [x] **Run the benchmark and baseline latency overhead.** Baseline on `llama3.1:8b` (2026-06-20): PII 100%, avg overhead 686 ms, avg char delta −106. Re-run after model or hardware changes:
  ```bash
  python scripts/benchmark_response_formatter.py
  ```
  Target: PII preservation 100%; latency overhead < 2000 ms per reply.

- [x] **Tune or replace the formatter system prompt** if the model produces poor rephrasing. Inspect outputs with `RESPONSE_FORMATTER_ENABLED=true` and one test message. If the model ignores the "answer only what was asked" rule, add a few-shot example to the prompt.

- [ ] **Add per-tool formatter hints** for special cases (e.g. a multi-client list → compact table, or a notes list → numbered list). Wire them through `format_data_reply()` as an optional `hint` argument.

- [ ] **Extend `_PHONE_RE`** to cover regional formats used by the coach's clients.

---

### Tool Routing — Next Steps for Better Coverage

The current stack (lexicon → token → embedding → rerank → LLM fallback) handles the most common routing failures. The following steps would push coverage further.

#### High impact (do first)

- [ ] **Run the benchmark and measure the baseline.** Before further tuning, measure exactly where you stand:
  ```bash
  python scripts/benchmark_tool_routing.py
  python scripts/eval_tool_routing.py --backend token --hard --show-errors
  python scripts/eval_tool_routing.py --backend rerank --hard --show-errors
  ```
  The gap between token and rerank on the hard set quantifies how much the embed+rerank layer is contributing.

- [ ] **Grow `routing.jsonl` with real failure cases.** Add every message that was misrouted or deferred in production. Failures on the hard eval set are the highest-value additions. Use `POST /api/tools/classify` to inspect scores without restarting.
  ```bash
  curl -X POST http://localhost:8000/api/tools/classify \
    -H "Content-Type: application/json" \
    -d '{"message": "your failing message here"}'
  ```

- [ ] **Tune `TOOL_ROUTER_RERANK_THRESHOLD`.** The default (0.55) is conservative. Run the benchmark, check the deferred rate on the hard set, and lower the threshold if too many correct queries are being deferred. A value of 0.45–0.50 is worth testing.

- [ ] **Extend `lexicon.py` from production logs.** The current lexicon is hand-crafted. After running in production for a week, grep the logs for messages that were deferred (`_embed_available` probe OK but `classify_tool` returned None) and add any recurring synonym groups.

#### Medium impact

- [ ] **Improve the `_is_data_request` pattern.** The regex is deliberately broad. Log cases where it fires incorrectly (triggers LLM router for coaching questions) or misses (data request not caught). Tighten the pattern based on evidence.

- [ ] **Add an observability endpoint for near-misses.** When `classify_tool` returns None, log the top-3 scores so you can see whether the correct tool was close but below threshold. Wire this into the health/debug API.

- [ ] **Test LLM router fallback accuracy.** `app/core/llm_router.py` is only tested with mocked providers. Run a small manual evaluation: take 20 messages that were deferred by the fast path and check whether the LLM router classifies them correctly. If accuracy is below 90%, improve the `_SYSTEM_PROMPT` in `llm_router.py`.

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
# or
python3 -m unittest discover -s tests -p "test_*.py"
```
