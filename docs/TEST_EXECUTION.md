# Test Execution Contract

Automated tests in this repository are **deterministic, isolated, and offline by default**. Real external-service execution belongs to explicit opt-in **benchmarks** and **evaluations** under `scripts/`, not to `pytest tests/`.

Architecture decision: [ADR-0014](adr/0014-test-execution-contract.md).

---

## 1. Core invariant

| Tier | Runner | Network | Config source |
|------|--------|---------|---------------|
| **Unit tests** | `pytest tests/` | Mocked / in-process doubles only | `tests/conftest.py` pins (not developer `.env`) |
| **Local integration tests** | `pytest tests/` | Loopback only (e.g. FastAPI `TestClient`, SQLite temp DB) | Same pins + test-local overrides |
| **Opt-in live integration** | `pytest` with env flags | Real local services when explicitly enabled | Developer env + flags |
| **Benchmarks / evaluations** | `scripts/benchmark_*.py`, `scripts/eval_*.py` | Real providers when configured | Developer `.env` / CLI args |

---

## 2. Test taxonomy

### Automated tests (`tests/`)

- **53 modules**, flat layout — no nested `unit/` vs `integration/` directories.
- **Framework:** pytest runner; mostly `unittest.TestCase`; some bare pytest functions.
- **Phase / ticket tests:** `test_phase1`–`test_phase4`, SEC/REL/AI tickets in docstrings.
- **Domain tests:** filename prefix (`test_rag_*`, `test_tool_*`, …).

### Opt-in live integration (still under `tests/`, gated by env)

| Module | Flag | What it exercises |
|--------|------|-------------------|
| `test_rerank_integration.py` | `RUN_RERANK_INTEGRATION=1` (or cached ONNX model on disk) | Real fastembed cross-encoder |
| `test_llm_router_integration.py` | `RUN_LLM_ROUTER_INTEGRATION=1` (else skips if Ollama unreachable) | Live Ollama LLM router |

These are **not** benchmarks — they are regression guards for local model behaviour. They never run in CI.

### Benchmarks and evaluations (`scripts/` — not pytest)

| Script | Purpose |
|--------|---------|
| `scripts/benchmark_pipeline.py` | Full-pipeline smoke (`--offline` for CI) |
| `scripts/benchmark_*.py` | Latency / regression checks |
| `scripts/eval_*.py` | Accuracy on `data/eval/*.jsonl` |
| `data/eval/*.jsonl` | Labeled corpora consumed by eval scripts |

`tests/test_eval_llm_router.py` is an **offline guard** for the eval corpus/schema — it does not call Ollama.

---

## 3. Environment isolation

`tests/conftest.py` loads **before** any `app` import and:

1. **Force-sets** every pin in `tests/isolation_support.py::TEST_ENV_OVERRIDES` (overrides `.env` and shell exports).
2. **Mutates** the `settings` singleton to match (belt-and-suspenders for import-order edge cases).
3. **Redirects** `MEMORY_DB_PATH` to a temp SQLite file.
4. **Installs** a fail-fast socket guard (see §5).

Pin registry (must stay in sync): `docs/CONTRACTS.md` §4 and `scripts/check_contracts.py`.

### Why each pin

| Variable | Test value | Prevents |
|----------|------------|----------|
| `RAG_BACKEND` | `token` | Ollama embed auto-probe / hangs |
| `TOOL_ROUTER_BACKEND` | `token` | Embedding-based routing hitting real embed servers |
| `RESPONSE_FORMATTER_ENABLED` | `false` | Formatter LLM pass + reranker warm-up |
| `RAG_EMBED_PROVIDER` | `ollama` | `.env` `openai`/`openrouter` breaking Ollama-mocked embed tests |
| `RAG_EMBED_BASE_URL` | *(empty)* | Remote embed server from `.env` |
| `RAG_RERANK_PROVIDER` | `local` | Remote TEI/OpenAI-compat rerank from `.env` |
| `OPENAI_MODEL` / keys | *(empty)* | `OpenAIProvider` replacing Ollama in tool-loop tests |
| `OLLAMA_BASE_URL` etc. | `http://127.0.0.1:1` | Slow timeouts when mocks are missing — fails in milliseconds |

CI (`.github/workflows/tests.yml`) sets the three original pins explicitly; conftest pins the full set so local runs match CI even with a populated `.env`.

---

## 4. Unit-test external dependency policy

Unit tests **must not** call real:

- LLM providers (Ollama, OpenRouter, OpenAI-compat)
- Embedding or reranking services
- Hugging Face Hub downloads
- Remote HTTP APIs

**Required pattern:** mock `httpx` clients, patch `get_client`, patch `_get_encoder`, or use `AsyncMock` for provider methods. Tests that verify provider *resolution* construct `Settings(...)` explicitly or patch `settings` fields for that case only.

---

## 5. Network isolation (fail-fast)

`tests/isolation_support.py::install_network_guard()` patches `socket.socket.connect`:

- **Default:** allow loopback (`127.0.0.1`, `localhost`, `::1`) only.
- **Block:** all other outbound TCP with an immediate `RuntimeError` naming the Test Execution Contract.
- **Opt-in:** when `RUN_LLM_ROUTER_INTEGRATION=1` or `RUN_RERANK_INTEGRATION=1`, the guard is disabled so live local integration and HF Hub downloads can proceed.

This is not a substitute for mocking — it catches accidental leaks that env pins alone would miss.

---

## 6. Running tests

```bash
# Normal automated suite (offline, deterministic)
.venv/bin/python -m pytest tests/ -q

# Equivalent explicit pins (redundant with conftest, but documented for CI clarity)
RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false \
  .venv/bin/python -m pytest tests/ -q
```

**Never** `python -m unittest discover` — it skips `conftest.py` (auth 401s, real DB path).

### Opt-in live integration

```bash
RUN_RERANK_INTEGRATION=1 pytest tests/test_rerank_integration.py -v
RUN_LLM_ROUTER_INTEGRATION=1 pytest tests/test_llm_router_integration.py -v
```

### Benchmarks / evaluations (manual, not part of pytest)

See [BENCHMARKS.md](BENCHMARKS.md) and [SMALL_MODELS.md](SMALL_MODELS.md).

---

## 7. CI implications

- CI has no `.env` and no Ollama — conftest pins guarantee the same behaviour as a developer machine with production-like local config.
- Workflow runs: `ruff`, `check_contracts.py`, `check_doc_paths.py`, `mypy`, `coverage run -m pytest tests/`.
- Integration tests skip in CI; benchmarks are not invoked.

---

## 8. Adding new external dependencies

When adding a provider, client, or remote service:

1. Register any new test pin in `TEST_ENV_OVERRIDES`, `docs/CONTRACTS.md` §4, and `scripts/check_contracts.py`.
2. Add unit tests with mocks — no real network.
3. If live verification is needed, use `scripts/eval_*.py` or gate a `tests/test_*_integration.py` module on a `RUN_*_INTEGRATION` flag.
4. Update this doc if the taxonomy changes.
