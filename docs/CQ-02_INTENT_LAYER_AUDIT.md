# CQ-02 — Deterministic Intent Layer: Audit & Consolidation Plan

> **Status:** Investigation complete. **No code changed** (this task is report-first).
> **Author:** Claude (Opus 4.8) · **Date:** 2026-07-05
> **Rule:** Any consolidation that follows must not reduce the eval baselines below.

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
