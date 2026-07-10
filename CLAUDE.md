# Coach Assistant AI — AI session contract

## What this repo is

FastAPI coaching assistant that helps coaches manage clients and retrieve coaching knowledge.
Local chat model: Llama 3.1 8B via Ollama; persistence in SQLite; Open WebUI as the frontend
via an OpenAI-compatible API (`/v1/chat/completions`).

## Commands

```bash
# Tests — always use these env pins; without them pytest hangs waiting on Ollama
RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false \
  .venv/bin/python -m pytest tests/ -q

# Lint / types / run
.venv/bin/ruff check .
.venv/bin/python -m mypy app/
python3 main.py
```

Never use `unittest discover` — it skips `tests/conftest.py` (auth fails closed; real DB touched).

## Environment facts

- **CI:** Python 3.11, installs `requirements-dev.txt` (see `.github/workflows/tests.yml`).
- **Local:** `.python-version` = 3.12; `requires-python = ">=3.11"`.
- pyproject `[dependency-groups]` are **not** what CI/Docker install — edit `requirements*.txt` for deployable deps.
- mypy `ignore_errors = true` for: `app.core.tools`, `app.core.model_registry`, `app.rag.retriever`, `app.core.tool_router`, `app.api.chat`, `app.api.openai_compat` (`pyproject.toml`).

## Hard rules

1. `docs/` is documentation only. App data (tool cards, eval sets, knowledge) lives under `data/`.
2. One commit per roadmap task; never edit files outside that task's "Files allowed to change".
3. Magic strings and tool-name lists that must stay in sync are registered in `docs/CONTRACTS.md` (if this file does not exist yet, the corresponding roadmap task has not run).
4. Module layering / import rules: `docs/MODULE_MAP.md` (if this file does not exist yet, the corresponding roadmap task has not run).
5. OpenAI-compat wire formats: `docs/WIRE_FORMATS.md` (if this file does not exist yet, the corresponding roadmap task has not run).
6. Do not invent APIs, env vars, or constants — verify from code or the docs above.

## Roadmap pointer

Structured work items live in `docs/roadmap/`. Execution protocol: `docs/roadmap/README.md` §1.
Progress ledger: `docs/roadmap/STATUS.md`. One task per session; pick the first `TODO` whose deps are `DONE`.
