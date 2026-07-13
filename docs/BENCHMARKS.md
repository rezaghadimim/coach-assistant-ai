# Benchmarks & Fast Error Detection

**Not pytest.** Benchmarks and evaluations are explicit opt-in tooling for quality and
latency measurement with real providers. The automated test suite (`pytest tests/`) stays
offline by default — see [TEST_EXECUTION.md](TEST_EXECUTION.md).

Two goals, two tools:

1. **"Is everything good right now?"** → `scripts/benchmark_pipeline.py` — a
   full-pipeline smoke benchmark that exercises every layer and checks latency
   budgets. Run it on demand or from cron/CI; exit code 1 means something broke.
2. **"Tell me the moment something breaks."** → `/health` (now reports
   `degraded` + an `issues` list) + `scripts/watch_health.sh` (polls it and
   fires a desktop notification / terminal alert on any state change or new
   error-log line).

## 1. The pipeline benchmark

```bash
# Everything (needs Ollama running):
.venv/bin/python scripts/benchmark_pipeline.py

# Offline / CI (skips Ollama-dependent checks):
.venv/bin/python scripts/benchmark_pipeline.py --offline

# Machine-readable for automation:
.venv/bin/python scripts/benchmark_pipeline.py --json

# One check while debugging:
.venv/bin/python scripts/benchmark_pipeline.py --only rag.fallback

# Treat slow-but-working as failure (pre-deploy gate):
.venv/bin/python scripts/benchmark_pipeline.py --strict
```

### What each check verifies, and what a failure means

| Check | Verifies | If it FAILs |
|-------|----------|-------------|
| `config` | Settings coherence: rerank floor > stage-1 floor, `RAG_RETRIEVE_K ≥ RAG_TOP_K`, chunk size fits E5, `num_ctx ≥ 4096`, tool temperature 0 | Fix `.env` — these are misconfigurations, not runtime faults |
| `ollama` | Server reachable; chat + embed models pulled | Start Ollama / `ollama pull` the named model |
| `llm.complete` | One tiny chat completion round-trips | Model corrupt or OOM — check `ollama ps`, RAM |
| `embed.query` | Query embedding returns a sane vector | Embed model missing/broken; tool router + RAG stage-1 degrade to token matching |
| `rerank.score` | Cross-encoder loads, emits sigmoid scores, ranks relevant > irrelevant | Broken model cache — delete `data/rerank_cache` and rerun (auto-purge handles most cases) |
| `rag.index` | Knowledge ingest produces a non-empty index | Starter/private dirs missing or empty |
| `rag.retrieve` | A canonical coaching query retrieves grounded chunks | Thresholds too high, embed backend down, or index/embedding mismatch |
| `rag.abstain` | An off-topic query retrieves nothing | (WARN) grounding may inject noise — consider raising `RAG_RERANK_MIN_SCORE` |
| `rag.fallback` | **Regression guard**: with the reranker forcibly broken, retrieval still returns stage-1 results | The silent-empty-retrieval bug is back — see invariants in [SMALL_MODELS.md](SMALL_MODELS.md) §6 |
| `router.token` | Deterministic tool router classifies canonical utterances | `routing.jsonl` missing/corrupt or lexicon regression |
| `router.llm` | Constrained JSON classify picks the right tool | New chat model too weak for classification — see swap checklist |
| `formatter.pii` | LLM-formatted reply preserves email/phone verbatim (or deterministic fallback fired) | Never ship this state — set `RESPONSE_FORMATTER_ENABLED=false` until fixed |

**Latency budgets** are defined at the top of the script (`BUDGETS_MS`),
deliberately generous for CPU-only machines. `WARN` = worked but slower than
budget. After a hardware or model change, treat consistent WARNs as your cue to
tune (`RAG_RETRIEVE_K`, `RAG_RERANK_MAX_PASSAGE_CHARS` — see
[SMALL_MODELS.md](SMALL_MODELS.md) §5).

### When to run it

| Moment | Command |
|--------|---------|
| After swapping any model | full run, then the eval scripts in [SMALL_MODELS.md](SMALL_MODELS.md) §3 |
| After editing `.env` / config | full run (at minimum `--only config`) |
| After ingesting new knowledge | `--only rag.index`, `--only rag.retrieve` |
| Before deploy / in CI | `--offline --strict` (no Ollama in CI) plus the unit suite |
| Nightly cron on the prod box | `--json` (alert on exit code — see below) |

## 2. Fast error notification

Three layers, from fastest to broadest:

### a. Live watcher (seconds)

```bash
./scripts/watch_health.sh                # poll /health every 15s
INTERVAL=5 ./scripts/watch_health.sh     # tighter
```

Fires a **macOS desktop notification + red terminal line + bell** when:
- `/health` reports `status: "degraded"` (message includes the exact issues),
- the API stops responding entirely,
- a **new line is appended to the error log** (`logs/errors.log`) — this is the
  fastest signal, since every unhandled exception and provider failure is
  logged at ERROR level with a correlation id.

Alerts fire on *state change* only (no spam) and recovery is announced.

Enable the error log if you haven't (`.env`):

```
LOG_ERROR_FILE=logs/errors.log
```

Docker Compose already writes it to `/app/logs/errors.log` (mounted at `./logs`).

### b. `/health` endpoint (for any monitor)

`GET /health` now returns real status instead of an unconditional `"ok"`:

```json
{ "status": "degraded",
  "issues": ["ollama unreachable at http://localhost:11434"], ... }
```

Checked per request: Ollama server reachability, embed model probe, reranker
load state (`warming` during startup download), OpenRouter (only when
configured). Point any monitor (Uptime Kuma, cron + curl, Docker healthcheck)
at it and alert on `status != "ok"`. `GET /health/live` stays as the cheap
liveness probe for the container itself.

### c. Cron benchmark (minutes, catches quality drift)

```cron
*/30 * * * * cd /path/to/coach-assistant-ai && \
  .venv/bin/python scripts/benchmark_pipeline.py --json >> logs/benchmark.jsonl 2>&1 \
  || osascript -e 'display notification "pipeline benchmark FAILED" with title "Coach Assistant"'
```

The watcher tells you *something broke*; the cron benchmark tells you *what
still works end to end* (including things a health probe can't see, like
retrieval quality and PII preservation).

## 3. Reading a failure fast

Every chat message gets a 6-char correlation id in the logs. When an alert fires:

```bash
grep "msg=ab12cd" logs/errors.log          # or: docker compose logs coach-api | grep msg=ab12cd
```

Step logs use a fixed outcome vocabulary (`hit | miss | skip | block | ok |
preview | error | fail | fallback | hallucination`), so `grep -E
"fail|error|hallucination"` over recent logs is a complete error sweep.

## 4. Related harnesses (deeper, slower)

- `scripts/eval_tool_routing.py` — routing accuracy/F1 on the 307-example corpus
- `scripts/eval_llm_router.py` — constrained-classify accuracy (needs LLM)
- `scripts/eval_rag_grounding.py` — grounding/abstention quality
- `scripts/benchmark_formatter_hints.py` — formatter PII + latency benchmark
- `RUN_RERANK_INTEGRATION=1 pytest tests/test_rerank_integration.py` — real ONNX reranker end-to-end

Use the pipeline benchmark as the always-first triage step; drop into these
when it points at a specific layer.
