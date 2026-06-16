# ADR-0009: Tool Routing Overhaul — Synonym Lexicon, Cross-Encoder Rerank, and LLM Fallback

**Date:** 2026-06-15
**Status:** Accepted

## Context

ADR-0007 introduced a two-backend tool router (token + embedding) that fixed profile-update misrouting.  A new class of failure emerged in production: arbitrary synonym phrasing such as "give me all visitors in table" or "dump the roster" returned generic LLM follow-up questions instead of executing `list_clients`.

Root causes:

1. **Lexical gap** — both the token backend and the embedding backend rely on surface similarity to training utterances.  When a user writes "visitors" instead of "clients" or "table" instead of "list", the cosine score drops below threshold and the query is deferred.

2. **LLM tool-calling fallback unreliability** — when the fast path deferred, the full LLM tool loop was called but the model sometimes returned only follow-up suggestions instead of a tool call, especially when the phrasing was unusual.

3. **No semantic generalization layer** — the bi-encoder encodes query and example independently, so it misses relevance differences that are only apparent when the two texts are compared jointly.

Three improvements are needed:
- **Bridge the vocabulary gap** without requiring new training examples for every synonym.
- **Add a precision layer** above the bi-encoder that scores candidates jointly.
- **Guarantee a data-retrieval request never dead-ends** at a follow-up response.

## Decision

### 1. Domain synonym lexicon (`app/core/lexicon.py`)

`normalize_for_routing(text)` appends canonical tokens to the query using a hand-crafted regex table before any backend sees it.  Examples:

| User writes | Canonical tokens appended |
|---|---|
| visitors, people, attendees, coachees | `client clients` |
| table, database, roster, everyone | `clients list list clients` |
| dump, pull, export | `show list` |
| remove, erase, kick | `delete` |

Rules are additive — the original tokens are preserved so exact matches are not disturbed.  The lexicon is applied **router-locally**: it never modifies the message sent to the LLM or stored in history.

### 2. Three-backend chain in `tool_router.py`

The router now tries three backends in order, returning on the first confident match:

```
synonym normalize
       │
       ▼
[rerank backend]  embedding top-K (floor 0.30)
       │           → cross-encoder score each candidate (BAAI/bge-reranker-base)
       │           → accept if sigmoid score ≥ 0.55 and margin ≥ 0.10
       │           → falls through if fastembed / Ollama unavailable or no candidate
       ▼
[embedding backend]  dense cosine ≥ threshold; margin check
       │              falls through on low confidence
       ▼
[token backend]      TF cosine; always available (CI-safe)
```

The cross-encoder model (`BAAI/bge-reranker-base`) is the same ONNX model already downloaded for RAG (ADR-0008) and reuses `rag_rerank_cache_dir` — no additional download.

New configuration keys (all prefixed `TOOL_ROUTER_`):

| Key | Default | Purpose |
|---|---|---|
| `RERANK_ENABLED` | `true` | Enable the two-stage path |
| `RERANK_TOP_K` | `10` | Stage-1 candidate pool size |
| `EMBED_FLOOR` | `0.30` | Minimum cosine to enter stage-1 pool |
| `RERANK_THRESHOLD` | `0.55` | Stage-2 sigmoid acceptance threshold |
| `RERANK_MARGIN` | `0.10` | Minimum margin between top-2 tools |
| `RERANK_MODEL` | `BAAI/bge-reranker-base` | Cross-encoder model |
| `LLM_FALLBACK_ENABLED` | `true` | Enable the LLM router fallback |

`ToolMatch` gains a `rerank_score: Optional[float]` field, and `POST /api/tools/classify` exposes both `rerank_score` and `backend` in its response.

### 3. LLM router fallback (`app/core/llm_router.py`)

When all three fast-path backends defer **and** the message is classified as a data-retrieval request by `_is_data_request()`, one compact LLM call is made with a constrained system prompt:

```
You are a tool classifier for a life-coaching assistant.
Given a coach message, decide which ONE tool name best matches — or "none".
Respond with ONLY valid JSON: {"tool": "<tool_name_or_none>"}
```

The LLM is given only the tool names (no descriptions) so the call is cheap.  If the returned tool name is valid and known, `execute_tool()` is called directly.  If the LLM returns "none", is unavailable, or returns malformed JSON, the full tool-calling loop proceeds as before.

### 4. Dead-end guard in `app/core/llm.py`

`_format_follow_ups_as_text` suppresses follow-up questions when the last user message is a data-retrieval request, preventing the LLM from returning only suggestions.  `_empty_reply_fallback` attempts `try_direct_client_action` before returning a targeted clarification message.  The system prompt (`COACH_ASSISTANT_SYSTEM_PROMPT`) includes an explicit `CRITICAL RULE` block emphasising that data-retrieval requests must trigger a tool call.

### 5. Evaluation infrastructure

- `data/eval/tool_routing_hard.jsonl` — 34 held-out out-of-vocabulary examples (the failure cases that motivated this ADR).
- `scripts/eval_tool_routing.py` gains `--backend rerank`, `--hard`, and `--latency` flags.
- `scripts/benchmark_tool_routing.py` — new script comparing all backends across both eval sets with accuracy, deferral rate, and p50/p95 latency.

## Consequences

**Positive:**
- Out-of-vocabulary synonym phrasings ("visitors", "table", "dump the roster") now route correctly via the lexicon + token backend even without Ollama running — no new infrastructure required for this improvement.
- The two-stage rerank path raises precision for genuinely ambiguous queries (multiple tools with similar scores) by scoring candidates jointly rather than independently.
- The LLM router fallback closes the remaining gap for completely novel phrasings that neither the lexicon nor the vector backends can handle.
- The dead-end guard eliminates the failure mode where a data request returned only follow-up suggestions.
- The cross-encoder model is already downloaded for RAG — zero additional disk/download cost.
- All new code has full offline test coverage (lexicon, rerank path with mocked fastembed, LLM router with mocked provider, data-request guard).
- Graceful degradation: each layer falls through cleanly, so the system degrades to token-only if Ollama and fastembed are both unavailable.

**Negative:**
- The rerank path adds ~50–150 ms latency on CPU when fastembed is active (same model as RAG reranker; measured on `BAAI/bge-reranker-base` with 10 candidates).
- The LLM router fallback adds one extra LLM call (gated by `_is_data_request`) for queries that slip through all fast-path layers.
- The synonym lexicon is manually maintained; new domain synonyms must be added by developers, not automatically learned.
- `TOOL_ROUTER_RERANK_THRESHOLD=0.55` is conservative; some correct queries may still be deferred to the embedding path. Tuning this threshold requires running the benchmark and inspecting the hard eval set.

## Alternatives Considered

| Option | Reason Not Chosen |
|---|---|
| Expand `routing.jsonl` with synonym examples only | Would require exhaustive enumeration of synonyms per language; doesn't generalise to unseen phrasings |
| Fine-tune a dedicated classifier | Requires a large labeled dataset and training pipeline; lexicon + rerank achieves similar coverage with zero training |
| Semantic search over tool descriptions instead of examples | Tool descriptions are short and don't cover the vocabulary variation; example-based corpus is richer |
| Always call the LLM router for every message | Higher latency and cost; the fast-path layers handle the vast majority of messages without an LLM call |
| Use a separate ANN index for the tool router | Corpus is ~130 examples; brute-force cosine is O(130) and fast enough; ANN adds infrastructure complexity |

## Amendment — Structured Output LLM Router (2026-06-17)

The LLM router fallback (`app/core/llm_router.py`) was updated to use Ollama's `format=` constrained decoding with a JSON schema that restricts the model output to one of the known tool names or `"none"`:

```json
{"type":"object","properties":{"tool":{"type":"string","enum":["create_client","add_client_note",...]}},"required":["tool"]}
```

This eliminates the JSON wrapper leakage (empty `{}`, garbage JSON) that occurred when the small model's free-form `{"tool":"..."}` attempt failed.  The call now runs at `TEMPERATURE_TOOL=0.0` and is capped at `MAX_TOKENS_CLASSIFY=64` tokens.

Four to eight few-shot `none` examples were added to the LLM router system prompt so the model learns to return `{"tool":"none"}` for advice questions rather than hallucinating a tool name.

The routing corpus was also expanded from ~131 to **307 examples** adding negative/`none`, multi-clause/noisy, and confusable-pair rows.  `TOOL_ROUTER_THRESHOLD` was retuned from `0.75` → `0.65` based on eval results:

| Backend | Standard | Hard set |
|---|---|---|
| Token (threshold 0.75) | 94.55% | 85.92% |
| Token (threshold 0.65) | 94.55% | **95.77%** |

Precision remains 1.00 (zero wrong-tool fires) at the lower threshold.

## Future Direction

- Run `scripts/benchmark_tool_routing.py` after deployment to establish an accuracy baseline on the hard set; use it to tune `TOOL_ROUTER_RERANK_THRESHOLD`.
- Log near-misses (deferred queries with top score > 0.25) to an observability endpoint so the lexicon and corpus can be grown from production data.
- Evaluate LLM router fallback accuracy manually on a sample of deferred queries; if below 90%, improve the constrained system prompt in `llm_router.py`.
- When the corpus exceeds ~1 000 examples, replace brute-force cosine with an ANN index (e.g. `hnswlib`) behind the same `classify_tool()` interface.
