# T-016 — Create docs/CONFIG.md (env-var reference, audited)

**Phase:** 1 · **Complexity:** M · **Estimated session:** ~600 lines input; one new ~150-line file
**Risks addressed:** R-20

## Goal
A single audited reference of every settings field: env name, default, read sites, and the non-obvious couplings.

## Why this task exists
Settings knowledge is scattered (a partial table in RAG.md, others in TOOL_ROUTING.md/OPERATIONS.md) and has quirks a model will guess wrong (R-20): `TOOL_ROUTER_USE_E5_PREFIX` is read by embed providers; two rerank namespaces drive one model; `rag_backend` values `auto` and `embedding` behave identically; legacy aliases (`OLLAMA_EMBED_MODEL`, `RAG_DOCS_DIR`, …) still work; `OPENAI_MODEL` silently swaps the local provider class.

## Context required
- `docs/roadmap/README.md` §1
- this file
- `app/core/config.py` (entire file, ~379 lines) — the single source of truth

## Files allowed to change
- `docs/CONFIG.md` (create)

## Files forbidden to change
Everything else — especially `app/core/config.py` and the existing env tables in RAG.md/TOOL_ROUTING.md (leave them; add no duplicates elsewhere).

## Dependencies
None.

## Preconditions
```bash
test ! -f docs/CONFIG.md && echo OK
wc -l app/core/config.py     # ~379
```

## Steps
1. Walk `app/core/config.py` top to bottom. For every `Settings` field, record: field name, env var(s) incl. `AliasChoices`, default, one-line meaning (from the field's comment/context — do not invent).
2. Group into sections: Auth/Debug, LLM providers, Temperatures, RAG retrieval, RAG rerank, Tool router, Embeddings, Memory/summary, Observability, Paths, Timeouts.
3. Add a **"Gotchas"** section documenting (verify each): `TOOL_ROUTER_USE_E5_PREFIX` read in `app/core/embed_providers/__init__.py` and `embed_providers/ollama.py`; `rag_rerank_*` vs `tool_router_rerank_*` both driving the same physical model; `rag_backend` `auto`≡`embedding` (`app/rag/retriever.py:709-714`); `OPENAI_MODEL` provider swap (`app/core/model_registry.py:82`); legacy alias migration in `config.py:301-328`; docker-URL rewriting model_validators (`config.py:301-377`).
4. Header: `Source of truth: app/core/config.py. This file is a rendered reference — when they disagree, config.py wins; fix this file.`
5. Validation, commit `T-016: Create docs/CONFIG.md (env-var reference)`.

## Acceptance criteria
- Every field present in `config.py` appears exactly once in CONFIG.md (spot-check: pick 10 random fields, confirm).
- Gotchas section covers all six items, each verified.

## Required tests
None (docs-only). Standard validation block still required.

## Validation (run exactly)
```bash
.venv/bin/ruff check .
.venv/bin/python -m mypy app/
RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false \
  .venv/bin/python -m pytest tests/ -q
```

## Documentation updates
This task IS documentation.

## ADR impact
None.

## Definition of Done
Acceptance criteria met; validation passes; single commit; STATUS.md updated.

## Rollback plan
`git revert <commit>` — new file only.
