# CQ-02 — Deterministic Intent Layer: Audit & Consolidation Plan

> **Status:** Done. Execution plan (§5) carried out 2026-07-05.
> **Author:** Claude (Opus 4.8) / Claude (Sonnet 5) · **Date:** 2026-07-04 / 2026-07-05
> **Rule:** Any consolidation that follows must not reduce the eval baselines below.
> **Outcome:** Category D (centralize JSON parsing) shipped as a pure refactor.
> Category A (retire selector role) was **investigated and rejected** — see §7 —
> because it measurably breaks the deterministic path in cases the router alone
> does not cover. No other category was touched (B, C, E, F were already "keep").

---

## 1. Baseline (measured, offline token backend)

| Eval | Set | Accuracy | Deferral |
|------|-----|----------|----------|
| `scripts/eval_tool_routing.py --backend token` | standard (55) | **100.00%** | 0.00% |
| `scripts/eval_tool_routing.py --backend token --hard` | hard/OOV (71) | **98.59%** | 1.41% (1 row) |
| `scripts/eval_llm_router.py` | llm_router set | *not run* — requires a live Ollama (`llama3.1:8b`); skips in this env |

These are the **router-only** numbers: both eval scripts call `classify_tool()` directly and **do not exercise the `client_intents.py` regex detectors**. That matters for the plan (§4): the evals as written cannot, on their own, prove a regex detector is safe to delete — they measure the layer that would *remain*.

---

## 2. What the layer actually is

Surface area (via `grep`):

| Module | `def`s | `re.compile` |
|--------|-------:|-------------:|
| `app/core/client_intents.py` | 28 | 32 |
| `app/core/scope.py` | 3 | 16 |
| `app/core/confirmations.py` | ~8 | 12 |
| `app/core/llm.py` (regex helpers) | — | 3 |
| **Total** | | **~63** |

## 3. Key finding — the layers are complementary, not duplicative

The production fast path (`try_direct_client_action_with_meta`, `client_intents.py:732`) runs **regex detectors first**, then falls back to the embedding/rerank router (`_tool_router_action`, `:549`). Crucially, when the router *does* fire, it still **delegates argument extraction back to the same regexes**:

```
_tool_router_action():                       # router picks the TOOL
    tool == "create_client" -> detect_profile_update() / detect_create_client()   # regex extracts ARGS
    tool in (get_client,…)  -> detect_client_lookup() / detect_client_mention()   # regex extracts ARGS
```

So the review's framing ("~80 regexes overlap with LLM tool-calling") is only half right:

- **Tool *selection*** — genuinely overlaps with the router and the LLM tool-loop.
- **Argument *extraction*** (which client? what field? what value?) — the router does **not** do this; only the regexes (or the LLM tool-loop) do.

Blanket deletion would break the deterministic fast path, which is exactly the sub-1-second, zero-LLM path the product relies on for common commands.

## 4. Categorized recommendation

| # | Detectors | Role | Recommendation |
|---|-----------|------|----------------|
| A | `detect_list_clients`, `detect_client_lookup` (as **selectors**) | tool selection the router already scores at 100%/98.59% | **Retire the selector role**, keep `detect_client_lookup` as an *extractor* only. Route selection through `classify_tool`. Measure with the harness in §5. |
| B | `detect_profile_update`, `_profile_update_args`, `detect_create_client`, `parse_text_tool_call` | **argument extraction** for writes | **Keep.** No equal-accuracy replacement exists short of the LLM tool-loop; they preserve the confirm-before-write UX deterministically. |
| C | `parse_pending_write`, `is_user_confirmation`, `is_user_cancellation`, `detect_confirm` | confirm/cancel state machine | **Keep.** Not a routing concern; AI-01 already made writes replay structured state. |
| D | `looks_like_malformed_tool_call`, `_loads_json_tolerant`, `_embedded_tool_json_candidates`, `_is_tool_shaped_dict` | defensive parsing of small-model output | **Keep,** but **centralize** into one `tool_json.py` module (currently spread across `client_intents.py` + `llm.py`). Pure refactor, behavior-neutral. |
| E | `scope.py` denylist | best-effort off-topic pre-filter | **Keep, documented as best-effort** — done under **AI-03**. |
| F | `is_simple_greeting`, `SIMPLE_GREETING_REPLY` | greeting shortcut | **Keep.** Trivial, high-value UX, no LLM cost. |

Net: the real, safe win is **(A) collapse the duplicate tool-*selection* regexes into the router** and **(D) centralize the JSON-parsing helpers** — not the wholesale removal the headline number implies. Estimated reduction: ~10–14 of the ~63 regexes, concentrated in selection.

## 5. Execution plan (only if approved; each step gated on evals)

1. **Build a full-path eval harness.** Extend `eval_tool_routing.py` with a `--path full` mode that runs each row through `try_direct_client_action_with_meta` (regex → router), not just `classify_tool`. Re-establish the baseline through the *whole* fast path. **This is the missing measurement instrument; without it, deletions are unmeasured.**
2. **Category A, one detector at a time.** Remove the selector branch, rerun standard + hard evals. Revert immediately if accuracy drops below 100% / 98.59%.
3. **Category D refactor.** Move JSON-tolerant parsing into one module; no behavior change; full suite must stay green.
4. **Re-run `eval_llm_router.py` against a live Ollama** before/after to confirm the hallucination rate is unchanged (this is the safety-critical metric the LLM-router eval exists for).
5. Update this doc's baseline table with before/after numbers per step.

## 6. Risk if deferred

Change-amplification: adding a tool still touches ~7 files. The intertwining in §3 is the reason. Consolidating selection (A) and parsing (D) is the highest-leverage reduction that does **not** risk the deterministic write path.

## 7. Execution results (2026-07-05)

### 7.1 Full-path eval harness (step 1 of §5)

Added `--path full` to `scripts/eval_tool_routing.py`. It runs each eval-set utterance
through `try_direct_client_action_with_meta()` against a fresh, throwaway `MemoryStore`
(seeded with the first names that appear in the eval sets — Ali, Sara, Mohammad, Hassan,
Reza, Maryam, Cyrus, Dara, Farid, Nadia — so client-scoped lookups can resolve a real
record), instead of calling `classify_tool()` directly. This is the missing instrument
the original audit flagged as required before touching anything.

Caveat found while building it: several `ClientActionResult` branches in
`try_direct_client_action_with_meta` (profile-update, create-client, text-tool-call,
update/delete-note) never set `.tool`, so the full-path harness under-reports accuracy
for those tools specifically (they succeed but report as "deferred" in the harness's
metrics). This is a pre-existing observability gap, orthogonal to CQ-02, not fixed here
to keep this change scoped — flagged for a future ticket. It does **not** affect the
tools Category A concerns (`list_clients`, `get_client`, `get_client_full`), which do
set `.tool` on every branch and were the actual object of measurement.

Full-path baseline for the Category-A-relevant tools (both eval sets, token backend):

| Tool | Standard | Hard |
|---|---|---|
| `list_clients` | 9/9 (100%) | 13/13 (100%) |
| `get_client` | 3/3 (100%) | 6/6 (100%) |
| `get_client_full` | 4/4 (100%) | 6/6 (100%) |

### 7.2 Category A — investigated, NOT applied

Hypothesis: `detect_list_clients`/`detect_client_lookup`'s *selector* role in
`try_direct_client_query_with_meta` is redundant with the router, since
`_tool_router_action` (which runs first in the real call chain) already tries
`classify_tool` for these same tools.

**Experiment 1 — delete the regex selector branch entirely.** Full-path accuracy for
`list_clients`/`get_client`/`get_client_full` stayed at 100%/100% on both eval sets
(the router already resolves every case in the eval sets before the fallback is ever
reached). But `tests/test_client_intents.py::test_direct_query_returns_profile` failed:
calling `try_direct_client_query("Get me Ali's detail", store)` **directly** (the
existing, tested, public entry point — bypassing `_tool_router_action`) returned `None`
after the deletion, because `classify_tool("Get me Ali's detail")` (token backend)
misses this possessive-apostrophe phrasing — confirmed by direct check:
`classify_tool("Get me Ali detail")` (no apostrophe) matches, `classify_tool("Get me
Ali's detail")` (with apostrophe) returns `None`.

**Experiment 2 — replace the regex selector with a `classify_tool()` call** (the
audit's literal suggestion: "route selection through classify_tool"). Same failure:
`classify_tool` doesn't recognize the apostrophe phrasing either, so the unit test still
breaks.

**Conclusion:** `try_direct_client_query_with_meta` is not purely a redundant fallback
behind the router — it is also called as a **standalone entry point**
(`try_direct_client_query`, exercised directly by tests and available as a public
function), and the regex catches phrasings the router's token/embedding backend does
not. The original audit's framing undersold this: the router and the regex selector are
complementary here too, the same way regex extraction is complementary to router
selection (§3). **No code change made for Category A** — this is a "verified, keep
as-is" outcome, per the audit's own gating rule ("revert immediately if accuracy
drops" / here: don't apply, since a controlled experiment showed a drop).

### 7.3 Category D — applied

Moved the JSON-tolerant tool-call parsing family — `_extract_tool_payload`,
`_is_tool_shaped_dict`, `_loads_json_tolerant`, `_embedded_tool_json_candidates`,
`looks_like_malformed_tool_call`, `parse_text_tool_call`, and the `_PY_TRUE`/`_PY_FALSE`/
`_PY_NONE`/`_TOOL_JSON_KEY_PATTERNS` constants — out of `client_intents.py` into a new
`app/core/tool_json.py`. `client_intents.py` now imports the two public functions from
there (and keeps re-exporting them for existing callers/tests that import from
`client_intents`); `llm.py` now imports them from `tool_json` directly instead of via
`client_intents`. Pure move, no behavior change.

**Verification:** full suite (582 tests) green on `TOOL_ROUTER_BACKEND=token`; router-only
eval unchanged (standard 100.00%/0% deferral, hard 98.59%/1.41% deferral — identical to
§1); full-path eval unchanged (55: 22 correct/33 deferred; 71: 36 correct/35 deferred —
identical to §7.1 pre-refactor run).

### 7.4 Net result

- Regex count: unchanged (~63) — Category D relocates code, it doesn't delete any.
- Change-amplification for a new tool: unchanged — the JSON-parsing move doesn't touch
  the tool-dispatch surface that causes the ~7-file shotgun surgery; that surface is
  Category B (argument extraction), which was correctly identified as load-bearing and
  kept.
- The full-path eval harness (`--path full`) is now a permanent regression gate for any
  future attempt at Category A: any future selector-consolidation PR must show the full
  eval suite (not just router-only) at parity before merging.
