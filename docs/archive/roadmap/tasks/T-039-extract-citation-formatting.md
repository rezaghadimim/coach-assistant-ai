# T-039 — Split retriever.py: extract citation/prompt formatting

**Phase:** 3 · **Complexity:** L · **Estimated session:** ~1,000 lines input; code-move diff
**Risks addressed:** R-08

## Goal
The citation/prompt-formatting block of `app/rag/retriever.py` (~lines 371–437 and 602–625: the `format_*` functions, `_format_chunk_citation`, `_format_expert_header`) moves to a new `app/rag/formatting.py`. Combined with T-038, retriever.py drops toward ~750 lines.

## Why this task exists
Same as T-038 (R-08): retriever.py mixes ranking math with presentation. Formatting is presentation — it consumes `RetrievedChunk`s and produces strings, touching no index state. Models editing citation wording currently load 912 lines of ranking code as collateral context.

## Context required
- `docs/roadmap/README.md` §1
- this file
- `app/rag/retriever.py` — lines 350–640 (locate the exact formatting functions; line numbers have shifted after T-038 — go by function names)
- `grep -rn "format_expert\|format_chunk\|_format_chunk_citation\|_format_expert_header" app/ tests/` — all call sites
- `docs/MODULE_MAP.md`

## Files allowed to change
- `app/rag/formatting.py` (create)
- `app/rag/retriever.py` (remove moved code; re-export moved public names from retriever for compatibility: `from app.rag.formatting import format_... # re-export`)
- `app/rag/expert_ideas.py` (import site only, if it calls the moved functions — check with the grep)
- Tests: patch-target strings only, if needed

## Files forbidden to change
- Any output string content — citations/prompts must be byte-identical.
- Everything else.

## Dependencies
T-038.

## Preconditions
```bash
grep -n "def format_\|def _format_" app/rag/retriever.py     # the formatting functions exist in retriever
git log --oneline -5                                          # confirm T-038 commit present
```

## Steps
1. From the grep, build the exact list of formatting functions and their callers (inside retriever, in `expert_ideas.py`, in `app/api/*` or `app/core/llm.py` — follow every hit).
2. Move the functions verbatim to `app/rag/formatting.py` (imports of `RetrievedChunk` etc. from retriever are fine — formatting sits above retriever's data types; check no cycle: retriever must not import formatting at module level EXCEPT for the compatibility re-exports — if retriever's own code calls a moved function internally, import it inside that function, matching codebase convention).
3. Add re-exports in retriever for public moved names.
4. Validation, commit `T-039: Extract citation formatting from retriever`.

## Acceptance criteria
- Formatting functions live in `formatting.py`; `git diff` shows moves, not rewrites.
- Full suite green with no assertion changes (string outputs unchanged).
- `wc -l app/rag/retriever.py` ≤ ~800.

## Required tests
Full regression suite; especially `tests/test_expert_ideas.py`, `tests/test_two_phase_retrieval.py`, `tests/test_phase2_rag_integration.py`.

## Validation (run exactly)
```bash
.venv/bin/ruff check .
.venv/bin/python -m mypy app/
RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false \
  .venv/bin/python -m pytest tests/ -q
```

## Documentation updates
docs/MODULE_MAP.md ownership table: add `formatting.py`.

## ADR impact
None.

## Definition of Done
Acceptance criteria met; validation passes; single commit; STATUS.md updated.

## Rollback plan
`git revert <commit>` — pure move with re-exports.
