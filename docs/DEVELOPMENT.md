# Development guide

How to set up, run, lint, type-check, and test this repo.  
Terse AI contract (same commands): root [`CLAUDE.md`](../CLAUDE.md).

## 1. Setup

- **Python version story (as of 2026-07-10):** local `.python-version` = **3.12**; CI uses **3.11** (`.github/workflows/tests.yml`); `requires-python = ">=3.11"`. Alignment is roadmap **T-050** / ADR-0013 (not landed yet). Prefer 3.11 locally if you want to match CI exactly.
- Create a venv and install **requirements files** (what CI/Docker install — **not** pyproject `[dependency-groups]`):

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

## 2. Running the app

Prerequisites and Compose details live in the root [README](../README.md) and [OPERATIONS.md](OPERATIONS.md). Minimal local path:

1. Ollama running with the configured chat model (default `llama3.1:8b`).
2. From the repo root: `python3 main.py` (or the Compose stack in the README).

## 3. Testing

Use **pytest only**. `tests/conftest.py` pins deterministic offline behaviour (full contract in [TEST_EXECUTION.md](TEST_EXECUTION.md)) — you do **not** need to unset your `.env` for a normal local run:

```bash
.venv/bin/python -m pytest tests/ -q
```

CI also sets these env vars explicitly (redundant with conftest, kept for visibility in `.github/workflows/tests.yml`):

```bash
RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false \
  .venv/bin/python -m pytest tests/ -q
```

Why the three CI-visible pins:

| Env | Why |
|-----|-----|
| `RAG_BACKEND=token` | Avoids embedding probes / Ollama network hangs |
| `TOOL_ROUTER_BACKEND=token` | Same for the tool router |
| `RESPONSE_FORMATTER_ENABLED=false` | Skips formatter LLM calls and related model downloads |

Additional pins (embed/rerank provider, API keys, dead-letter base URLs) are applied automatically by conftest — see [CONTRACTS.md](CONTRACTS.md) §4.

**Never** `python -m unittest discover`: it skips `tests/conftest.py`, which sets `DEBUG=true` and a temp `MEMORY_DB_PATH`. Without that, auth fails closed (401s) and tests can touch the real `data/coach_assistant.db`.

Optional live / heavy tests gate on env flags (no pytest marks), e.g. `RUN_RERANK_INTEGRATION=1`. See [TEST_EXECUTION.md](TEST_EXECUTION.md) §2.

Benchmarks and evaluations (`scripts/benchmark_*.py`, `scripts/eval_*.py`) are **not** pytest — see [BENCHMARKS.md](BENCHMARKS.md).

## 4. Lint & types

```bash
.venv/bin/ruff check .          # E,F only; E501 ignored (see pyproject.toml)
.venv/bin/python -m mypy app/   # non-strict
```

mypy currently `ignore_errors = true` for: `app.core.tools`, `app.rag.retriever`, `app.core.tool_router`, `app.api.chat`, `app.api.openai_compat`. `app.core.model_registry` was un-ignored in roadmap **T-040**.

## 5. Working a roadmap task

From [`docs/roadmap/README.md`](roadmap/README.md) §1:

1. Read `STATUS.md`; pick the first `TODO` whose dependencies are `DONE`.
2. Open only that task file; read only the files it lists.
3. Change only “Files allowed to change”; run its validation block.
4. One commit `T-xxx: <title>`; update `STATUS.md` in the same commit.
5. On uncertainty or unexpected failure: stop, revert, record notes in `STATUS.md`.

## 6. What lives where

| Path | Role |
|------|------|
| `docs/` | Documentation only |
| `data/` | App data (tool cards, eval sets, knowledge, caches, SQLite) |
| Scratch / `artifacts/` / generated graphs | Local only — never commit |
