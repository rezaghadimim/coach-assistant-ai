# Coach Assistant AI — AI session contract

## What this repo is

FastAPI coaching assistant that helps coaches manage clients and retrieve coaching knowledge.
Local chat model: Llama 3.1 8B via Ollama; persistence in SQLite; Open WebUI as the frontend
via an OpenAI-compatible API (`/v1/chat/completions`).

## Commands

```bash
# Tests — conftest pins offline behaviour; explicit CI pins optional
.venv/bin/python -m pytest tests/ -q

# Lint / types / run
.venv/bin/ruff check .
.venv/bin/python -m mypy app/
python3 main.py
```

Never use `unittest discover` — it skips `tests/conftest.py` (auth fails closed; real DB touched).

## Environment facts

- **Python:** **3.12 only** everywhere (local `.python-version`, CI, Docker, `requires-python`, ruff `py312`, mypy). CI installs `requirements-dev.txt`.
- pyproject `[dependency-groups]` are **not** what CI/Docker install — edit `requirements*.txt` for deployable deps.
- mypy `ignore_errors = true` for: `app.core.tools`, `app.rag.retriever`, `app.core.tool_router`, `app.api.chat`, `app.api.openai_compat` (`pyproject.toml`).
- **Tenancy:** one coaching practice per deployment (one `API_KEY`, one SQLite). Scale with separate containers; uvicorn `--workers 1` by design.
- **Deps:** requirements files are authoritative for CI/Docker (not pyproject dependency-groups).

## Hard rules

1. `docs/` is documentation only. App data (tool cards, eval sets, knowledge) lives under `data/`.
2. Magic strings and tool-name lists that must stay in sync: `docs/CONTRACTS.md`.
3. Module layering / import rules / process state: `docs/MODULE_MAP.md`.
4. OpenAI-compat wire formats: `docs/WIRE_FORMATS.md`.
5. Do not invent APIs, env vars, or constants — verify from code or the docs above.
6. Test execution contract: `docs/TEST_EXECUTION.md` (ADR-0014). Automated tests are offline by default; benchmarks/evals live under `scripts/`.
7. **Do not open `docs/archive/` or `docs/roadmap/`** (except the short redirect at `docs/roadmap/README.md`) unless the user explicitly asks for historical audit/roadmap context. Those trees are finished archives and waste tokens.

## Living docs (prefer these)

| Doc | When to read |
|-----|----------------|
| `docs/MODULE_MAP.md` | Imports, singletons, layering |
| `docs/CONVENTIONS.md` | Coding patterns |
| `docs/CONTRACTS.md` | Must-match strings / tool names |
| `docs/WIRE_FORMATS.md` | `/v1/chat/completions` shapes |
| `docs/CONFIG.md` | Env vars |
| `docs/DEVELOPMENT.md` | Setup / lint / test |
| `docs/OPERATIONS.md` | Deploy / workers / ops |

New product work: edit code + living docs above. Do **not** invent new `T-xxx` roadmap tasks unless the user asks.
