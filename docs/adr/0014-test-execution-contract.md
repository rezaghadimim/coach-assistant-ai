# ADR-0014: Test execution contract

**Date:** 2026-07-13
**Status:** Accepted

## Context

The automated test suite had three recurring problems:

1. **Developer `.env` leaked into pytest** — production-like `RAG_EMBED_PROVIDER`, `RAG_RERANK_PROVIDER`, `OPENAI_MODEL`, and remote base URLs caused unit tests to hit real services, producing ~22-minute runs with SSL handshake timeouts instead of fast deterministic failures.
2. **No single policy** — CI pinned three env vars; conftest used `setdefault` (which does not override pydantic-settings `.env` loading); individual test modules duplicated partial pins.
3. **Benchmark/eval vs test boundary was implicit** — `scripts/eval_*.py` and `scripts/benchmark_*.py` are the established quality-measurement path, but nothing documented that pytest must stay offline.

ADR-0007 and ADR-0009 require CI-safe offline tests for embed/rerank/router paths. This ADR formalizes how that requirement is enforced repo-wide.

## Decision

### Test taxonomy

| Category | Location | Default execution |
|----------|----------|-------------------|
| Unit tests | `tests/test_*.py` (mocked boundaries) | Always in CI and local `pytest tests/` |
| Local integration tests | `tests/test_phase*.py`, FastAPI `TestClient` | Always — loopback only |
| Opt-in live integration | `test_rerank_integration.py`, `test_llm_router_integration.py` | Skip unless env flag or local cache |
| Benchmarks | `scripts/benchmark_*.py` | Manual / cron — never pytest |
| Evaluations | `scripts/eval_*.py` + `data/eval/` | Manual — never pytest |
| Eval guards | `test_eval_llm_router.py` | Offline schema checks only |

### Unit-test external dependency policy

Unit tests must mock, fake, or stub every external boundary (LLM, embed, rerank, HTTP, HF Hub). No real provider calls.

### Integration-test infrastructure policy

Integration tests use in-process FastAPI `TestClient`, temp directories, and ephemeral SQLite (`MEMORY_DB_PATH` in conftest). No shared staging/production infrastructure. Live Ollama/fastembed runs require explicit `RUN_*_INTEGRATION=1` flags and are excluded from CI.

### Benchmark/evaluation policy

Quality, latency, and provider-comparison runs use existing `scripts/benchmark_*.py` and `scripts/eval_*.py` conventions documented in `docs/BENCHMARKS.md`. They require developer credentials and are never collected by pytest.

### Environment isolation

`tests/conftest.py` force-sets `TEST_ENV_OVERRIDES` (defined in `tests/isolation_support.py`) **before** `app.core.config` loads, then mutates the `settings` singleton. Pins are registered in `docs/CONTRACTS.md` §4 and verified by `scripts/check_contracts.py`.

### Network isolation and fail-fast behaviour

`install_network_guard()` patches `socket.socket.connect` to block non-loopback outbound TCP unless `RUN_LLM_ROUTER_INTEGRATION=1` or `RUN_RERANK_INTEGRATION=1`. Violations raise immediately with a contract message pointing to `docs/TEST_EXECUTION.md`.

Provider base URLs in test mode point at `http://127.0.0.1:1` so unmocked calls fail in milliseconds (connection refused), not after provider timeouts.

### CI implications

No workflow change beyond documentation — conftest makes CI env pins redundant but keeps them for visibility. Suite must pass without `.env`, without Ollama, and without network.

## Consequences

**Positive**

- Local and CI test behaviour are equivalent regardless of developer `.env`.
- Accidental external calls fail in milliseconds with an actionable message.
- Single documented contract (`docs/TEST_EXECUTION.md`) replaces scattered tribal knowledge (U-05).
- Pin list is machine-verified via `check_contracts.py`.

**Negative / trade-offs**

- Tests that intentionally verify provider resolution against custom `Settings(...)` must remain explicit — global pins do not affect freshly constructed `Settings` instances with explicit kwargs.
- Opt-in integration tests must set `RUN_*_INTEGRATION=1` before conftest installs the network guard (documented in `TEST_EXECUTION.md`).
- `OLLAMA_BASE_URL=http://127.0.0.1:1` means any test that forgets to mock Ollama gets connection refused — correct fail-fast, but requires mocks.

## Alternatives Considered

- **pytest-socket dependency** — rejected; a small in-repo guard avoids a new dev dependency and matches the existing “no pytest.ini” minimalism.
- **pytest markers (`@pytest.mark.integration`)** — rejected; repo convention gates live tests on env flags (see `docs/CONVENTIONS.md` §7).
- **Separate `tests/unit/` and `tests/integration/` trees** — rejected; flat `tests/` layout is established across 53 modules.
- **Disabling `.env` loading in tests via `SettingsConfigDict`** — rejected; would require app code changes and weaken production config loading; env force-set in conftest is sufficient.
