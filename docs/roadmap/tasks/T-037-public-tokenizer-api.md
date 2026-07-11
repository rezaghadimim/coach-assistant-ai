# T-037 — Public tokenizer/cosine API; end cross-module `_private` imports

**Phase:** 3 · **Complexity:** M · **Estimated session:** ~900 lines input; ~30-line diff across 4 files
**Risks addressed:** R-11, R-12

## Goal
`app/core/tool_router.py` and `app/core/intent_kb.py` import public names (`tokenize`, `tf_cosine`) instead of `_tokenize`/`_tf_cosine` from `app.rag.retriever`; the retriever exports them deliberately.

## Why this task exists
Cross-module imports of underscored names (R-11) invite two failure modes: a model "cleaning up" unused-looking privates breaks distant callers, and a model needing tokenization picks the WRONG same-named `_tokenize` (three exist with different semantics, R-12). A public, documented export makes the intended one unambiguous.

## Context required
- `docs/roadmap/README.md` §1
- this file
- `app/rag/retriever.py` — ONLY the bottom section (~lines 890–912: `_tf_cosine`, `_tokenize`)
- `app/core/tool_router.py` — only the import site (~line 52) and use sites (grep `_tf_cosine\|_tokenize`)
- `app/core/intent_kb.py` — only the import site (~line 22) and use sites

## Files allowed to change
- `app/rag/retriever.py` (add public aliases + docstring only — no logic changes)
- `app/core/tool_router.py`, `app/core/intent_kb.py` (import/use sites only)

## Files forbidden to change
- `app/rag/ingest.py` (its whitespace `_tokenize` is a different function — leave it; renaming it is out of scope)
- Everything else.

## Dependencies
T-013.

## Preconditions
```bash
grep -n "_tf_cosine\|_tokenize" app/core/tool_router.py app/core/intent_kb.py   # cross-module private imports exist
grep -n "def _tokenize\|def _tf_cosine" app/rag/retriever.py                    # definitions (~897-912)
```

## Steps
1. In `retriever.py`, directly below the two functions, add:
   ```python
   # Public API: tokenization/cosine used by tool_router and intent_kb.
   # The leading-underscore names are kept for internal/test compatibility.
   tokenize = _tokenize
   tf_cosine = _tf_cosine
   ```
   Note in the comment that `app/rag/ingest.py` has a DIFFERENT `_tokenize` (whitespace split) — do not conflate.
2. Update the two importing modules to import and use the public names. Keep import style (module-level vs in-function) exactly as it is at each site.
3. Validation, commit `T-037: Public tokenizer/cosine API`.

## Acceptance criteria
- `grep -rn "import.*_tf_cosine\|import.*_tokenize" app/core/` → 0 hits.
- Behavior identical: full suite green with no test edits (aliases, not moves).

## Required tests
Full regression suite; specifically `tests/test_tool_router.py`, `tests/test_intent_kb.py`.

## Validation (run exactly)
```bash
.venv/bin/ruff check .
.venv/bin/python -m mypy app/
RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false \
  .venv/bin/python -m pytest tests/ -q
```

## Documentation updates
docs/MODULE_MAP.md: update the R-11 violations list (these two resolved); docs/CONVENTIONS.md item 9 updated.

## ADR impact
None.

## Definition of Done
Acceptance criteria met; validation passes; single commit; STATUS.md updated.

## Rollback plan
`git revert <commit>` — aliases only, zero behavior change.
