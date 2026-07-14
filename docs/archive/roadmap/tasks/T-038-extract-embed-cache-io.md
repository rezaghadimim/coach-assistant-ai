# T-038 — Split retriever.py: extract embedding-cache I/O

**Phase:** 3 · **Complexity:** L · **Estimated session:** ~1,100 lines input; code-move diff
**Risks addressed:** R-08

## Goal
The embedding-cache persistence block of `app/rag/retriever.py` (~lines 803–894: `_corpus_cache_path`, `_cache_key`, `_load_cache`, `_save_cache`, `_CACHE_FORMAT_VERSION`) lives in a new `app/rag/embed_cache.py`. Retriever shrinks by ~90 lines; the cache format is unchanged byte-for-byte.

## Why this task exists
`retriever.py` (912 lines) cannot fit in an 8B context window with a task prompt (R-08). Cache I/O is the most self-contained seam: pure functions over paths and dicts, no index state.

## Context required
- `docs/roadmap/README.md` §1
- this file
- `app/rag/retriever.py` — read lines 780–912 fully, plus grep results for each moved symbol to find all internal call sites
- `docs/MODULE_MAP.md`

## Files allowed to change
- `app/rag/embed_cache.py` (create)
- `app/rag/retriever.py` (remove moved code; import from new module; keep `_cache_key = embed_cache.cache_key`-style aliases for any symbol referenced by tests)
- Tests: patch-target strings only, if any test patches the moved symbols (check `grep -rn "_load_cache\|_save_cache\|_cache_key\|_corpus_cache_path" tests/`)

## Files forbidden to change
- Cache file locations/format (`data/rag_index_cache*.json`) — byte-identical output required.
- `app/knowledge/ingest.py` (its divergent cache is T-036's business).
- Everything else.

## Dependencies
T-037 (retriever's public-API section settled first, avoiding merge collisions at the file bottom).

## Preconditions
```bash
grep -n "_CACHE_FORMAT_VERSION\|def _load_cache\|def _save_cache\|def _cache_key\|def _corpus_cache_path" app/rag/retriever.py   # all in ~803-894
grep -rn "_load_cache\|_save_cache" tests/ | wc -l    # record: number of test references
```

## Steps
1. Create `app/rag/embed_cache.py`; move the five symbols verbatim (public names: drop the leading underscore; module docstring describes the on-disk format: versioned header `{version, model, dim}`, key = `embed_profile_id::chunk_id::sha256(text)[:16]`).
2. In `retriever.py`, import the new module and delegate; keep old `_name = new_name` aliases if (and only if) the precondition grep found test references.
3. **Byte-format proof:** before your change, run a token-backend ingest that writes the cache? — No: cache writes require embeddings (network). Instead prove by inspection + unit test: add `tests/test_rag_ingest.py::test_embed_cache_roundtrip` (or new small test file) that calls save then load on a tmp path with a synthetic vector dict and asserts round-trip equality and the header fields. This runs offline.
4. Validation, commit `T-038: Extract embedding-cache I/O from retriever`.

## Acceptance criteria
- `wc -l app/rag/retriever.py` decreased by ≥ 80 lines; no logic edits inside moved functions (`git diff` shows moves, not rewrites).
- Round-trip test passes; full suite green.

## Required tests
Step-3 round-trip test; full regression suite (`tests/test_rag_ingest.py`, `tests/test_embeddings.py`, `tests/test_two_phase_retrieval.py` especially).

## Validation (run exactly)
```bash
.venv/bin/ruff check .
.venv/bin/python -m mypy app/
RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false \
  .venv/bin/python -m pytest tests/ -q
```

## Documentation updates
docs/MODULE_MAP.md ownership table: add `embed_cache.py`.

## ADR impact
None (intra-package move; format unchanged). ADR-0003 does not describe cache internals — verify with a grep for "cache" in it; update only if it does.

## Definition of Done
Acceptance criteria met; validation passes; single commit; STATUS.md updated.

## Rollback plan
`git revert <commit>` — cache format untouched, so on-disk caches remain valid in both directions.
