# T-006 — Correct IMPLEMENTATION.md and mark it historical

**Phase:** 0 · **Complexity:** S · **Estimated session:** ~500 lines input; small docs diff
**Risks addressed:** R-01

## Goal
`docs/IMPLEMENTATION.md` no longer asserts false current-state claims, and carries a banner declaring it a historical work log rather than current truth.

## Why this task exists
IMPLEMENTATION.md is a phase-by-phase changelog that has drifted: it claims guardrail coverage is A/B/C/D with non-PII fabrication as an open gap, while the code implements guardrail E (`_notes_grounded`, `app/core/llm.py`) which closes that gap and is tested. It also repeats the stale "307 examples" corpus count. A model reading it may re-implement an existing guardrail (R-01).

## Context required
- `docs/roadmap/README.md` §1
- this file
- `docs/IMPLEMENTATION.md` (entire file, ~371 lines)
- `docs/SMALL_MODELS.md` line ~6 only (correct "guardrails A/B/C/E" phrasing to copy)

## Files allowed to change
- `docs/IMPLEMENTATION.md`

## Files forbidden to change
Everything else — especially do NOT touch `app/core/llm.py` or `tests/test_llm_guardrails.py`; you are fixing the doc to match them, not vice versa.

## Dependencies
None.

## Preconditions (verify before editing)
```bash
grep -n "Residual gap" docs/IMPLEMENTATION.md          # hit near line 220
grep -n "307" docs/IMPLEMENTATION.md                   # hits near lines 157, 251, 261
grep -n "_notes_grounded" app/core/llm.py              # exists (guardrail E)
grep -n "notes_grounded\|guardrail" tests/test_llm_guardrails.py | head   # guard E is tested
```

## Steps
1. Add at the top of IMPLEMENTATION.md: `> **Historical work log.** Entries record the state at the time they were written and are not maintained. For current facts see ARCHITECTURE.md, docs/CONTRACTS.md, and the code.`
2. In the guardrail section (~lines 215–224): correct the guard list to A/B/C/E and replace the "Residual gap (documented, not fixed)" claim with a note that guardrail E (`_notes_grounded` in `app/core/llm.py`) now blocks fabricated note/goal/decision content and is covered by `tests/test_llm_guardrails.py`.
3. Replace "307" corpus-size claims with `363+ (count with: wc -l data/tool-knowledge/examples/routing.jsonl)`.
4. Validation, commit `T-006: Correct IMPLEMENTATION.md and mark it historical`.

## Acceptance criteria
- Banner present at top.
- No "Residual gap" claim about non-PII fabrication remains; guard E documented.
- `grep -n "307" docs/IMPLEMENTATION.md` → no corpus-size hits.

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
This task IS the documentation update.

## ADR impact
None.

## Definition of Done
Acceptance criteria met; validation passes; single commit; STATUS.md updated.

## Rollback plan
`git revert <commit>` — docs-only.
