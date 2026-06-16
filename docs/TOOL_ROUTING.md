# Tool Routing

## What it is

The tool router classifies a coach message into the best-matching tool *before* it reaches the LLM, using example-based similarity. This fixes the most common misrouting error: messages like **"Ali's age is 23"** being sent to `add_client_note` (inserts a new row every time) instead of `create_client` (merges profile fields).

It also handles **out-of-vocabulary synonyms** like "give me all visitors in table" → `list_clients` through a combination of domain synonym normalization, embedding similarity, and cross-encoder reranking.

## Routing pipeline

```
User message
  │
  ├─ Pending write confirmation? ────────────────────────── ConfirmOrCancel
  │
  ├─ Regex: profile fields, create/list patterns ─────────── execute_tool directly
  │
  ├─ Synonym normalization (lexicon.py) ───────────────────── expand query in-place
  │
  ├─ Tool Router ──────────────────────────────────────────── classify_tool()
  │     ├─ Stage 1: Embedding top-K recall (floor=0.30)
  │     ├─ Stage 2: Cross-encoder rerank (threshold=0.55)  ← best precision
  │     ├─ Embedding-only cosine (threshold=0.75)
  │     ├─ Token-frequency cosine (threshold=0.75)
  │     └─ param extractor ──────────────────────────────── execute_tool or defer
  │
  ├─ Regex + Intent KB (read-only queries) ───────────────── execute_tool or defer
  │
  ├─ LLM router fallback (constrained tool pick) ─────────── one compact LLM call
  │     └─ param extractor ──────────────────────────────── execute_tool or defer
  │
  └─ LLM tool calling loop (hardened prompt) ─────────────── last resort
        └─ data-request guard (no follow-ups-only dead-end)
```

**Key principle:** the router picks the *tool*; existing regex helpers extract *parameters*. If a tool is identified confidently but parameters cannot be parsed, the message falls through to the LLM — behavior is unchanged. Each layer degrades gracefully; no layer can hard-fail a request.

## Corpus

The routing corpus lives in `docs/tool-knowledge/`:

```text
docs/tool-knowledge/
  create_client.md          ← when to use, hard negatives
  add_client_note.md
  update_client_note.md
  delete_client_note.md
  delete_client.md
  get_client.md
  get_client_full.md
  list_client_notes.md
  list_clients.md
  examples/
    routing.jsonl           ← labeled utterances (source of truth)
```

Each `.md` explains **Use when** / **Do NOT use when** for that tool.

### routing.jsonl format

One JSON object per line:

```json
{"utterance": "Ali's age is 23", "tool": "create_client", "hint": "profile:age"}
{"utterance": "Note that Ali decided to change careers", "tool": "add_client_note", "hint": "note_type:decision"}
{"utterance": "What are Ali's goals?", "tool": "list_client_notes", "hint": "note_type:goal"}
{"utterance": "How can I help Ali feel less overwhelmed?", "tool": "none", "hint": "advice"}
```

Fields:
- `utterance` — example coach message (required)
- `tool` — correct tool name, or `"none"` for advice/general questions that must NOT fire a tool (required)
- `hint` — optional metadata, e.g. `"profile:age"`, `"note_type:goal"`, `"advice"` — used by param extraction

**Negative (`tool:"none"`) examples are critical.** Without them the router cannot learn the boundary between "save a goal for Ali" and "what's a good exercise for goal-setting?" — and the LLM gets called for advice questions unnecessarily.

The corpus is **English-only**.  `multilingual-e5-small` is the embed model for diverse English phrasing.

To add examples, edit `routing.jsonl` and call `POST /api/tools/reindex` (no restart required).

## Backends

| Backend | How it works | When to use |
|---------|-------------|-------------|
| `token` | Token-frequency cosine similarity (same math as RAG retriever) | Always available; CI default; no Ollama needed |
| `embedding` | Dense cosine over Ollama-generated vectors | More accurate for paraphrases and multilingual text; requires embed model |
| `auto` | Probes Ollama at startup; uses `embedding` if available, else `token`; adds rerank stage when fastembed is installed | **Recommended default** |

### Two-stage rerank (best coverage)

When `TOOL_ROUTER_RERANK_ENABLED=true` (default) and both Ollama embed model and `fastembed` are available, `auto` backend adds a rerank stage on top of embedding:

1. **Stage 1 — Embedding top-K recall**: embed the query, score all examples, take the top `TOOL_ROUTER_RERANK_TOP_K` (default 10) with cosine ≥ `TOOL_ROUTER_EMBED_FLOOR` (0.30).
2. **Stage 2 — Cross-encoder rerank**: run `BAAI/bge-reranker-base` (local ONNX via fastembed, no Ollama) over the stage-1 candidates. Accept if sigmoid score ≥ `TOOL_ROUTER_RERANK_THRESHOLD` (0.55) with `TOOL_ROUTER_RERANK_MARGIN` (0.10) over the runner-up tool.

The cross-encoder reads query + candidate utterance **jointly**, giving it far better synonym/paraphrase sensitivity than cosine alone. This is why "visitors in table" → `list_clients` works even when the embedding cosine is weak.

### Domain synonym normalization (lexicon)

`app/core/lexicon.py` expands out-of-vocabulary terms **before** matching:

- `visitor/person/people/contact/attendee/coachee/participant/patient` → appends `client clients`
- `table/database/db/records/roster/everyone/everybody` → appends `clients list list clients`
- Retrieval verbs: `dump/fetch/pull/grab/retrieve/display` → appends `show get list`
- And more (see `lexicon.py`)

Expansion is **additive** (original text preserved), router-local only (does not touch RAG).

## Setup

### 1. Pull the embed model

```bash
ollama pull karuniaperjuangan/multilingual-e5-small
```

Verify:

```bash
curl http://localhost:11434/api/embeddings \
  -d '{"model":"karuniaperjuangan/multilingual-e5-small","prompt":"query: Ali age is 23"}'
```

### 2. Install fastembed for cross-encoder reranking (optional but recommended)

```bash
pip install fastembed
```

The cross-encoder model (`BAAI/bge-reranker-base`) downloads automatically on first use and is cached under `data/rerank_cache/` (same as RAG reranker).

### 3. Configure (optional overrides in `.env`)

```env
TOOL_ROUTER_ENABLED=true
TOOL_ROUTER_BACKEND=auto
OLLAMA_EMBED_MODEL=karuniaperjuangan/multilingual-e5-small
TOOL_KNOWLEDGE_DIR=docs/tool-knowledge
# Tuned to 0.65 against 307-example corpus: 95.77% hard-set accuracy, precision 1.00.
TOOL_ROUTER_THRESHOLD=0.65
TOOL_ROUTER_MARGIN=0.08
TOOL_ROUTER_USE_E5_PREFIX=true

# Two-stage rerank settings
TOOL_ROUTER_RERANK_ENABLED=true
TOOL_ROUTER_RERANK_TOP_K=10
TOOL_ROUTER_EMBED_FLOOR=0.30
TOOL_ROUTER_RERANK_THRESHOLD=0.55
TOOL_ROUTER_RERANK_MARGIN=0.10
TOOL_ROUTER_RERANK_MODEL=BAAI/bge-reranker-base

# LLM router fallback (constrained single-call after fast path defers)
TOOL_ROUTER_LLM_FALLBACK_ENABLED=true
```

Docker users: the embed model must be pulled on the **host** Ollama. The API reaches it via `host.docker.internal:11434`. The `docs/tool-knowledge/` directory is mounted read-only into the container.

### 3. E5 prefix convention

`multilingual-e5-small` requires specific prefixes for best accuracy:
- User messages indexed as **passages**: `"passage: {text}"`
- Query at classify time: `"query: {text}"`

Set `TOOL_ROUTER_USE_E5_PREFIX=false` when using a model that does not expect these prefixes.

> The corpus is **English-only**. `multilingual-e5-small` is the recommended embed model because it handles diverse English phrasing well.

## API

### Classify a message

```bash
curl -X POST http://localhost:8000/api/tools/classify \
  -H "Content-Type: application/json" \
  -d '{"message": "Ali is 23 years old"}'
```

Response:

```json
{
  "message": "Ali is 23 years old",
  "tool": "create_client",
  "score": 0.99,
  "hint": "profile:age",
  "backend": "token",
  "top_n": [
    {"tool": "create_client", "score": 0.99, "hint": "profile:age", "utterance": "Ali is 23 years old"},
    {"tool": "add_client_note", "score": 0.12, "hint": "note_type:general", "utterance": "..."},
    {"tool": "list_client_notes", "score": 0.08, "hint": "note_type:goal", "utterance": "..."}
  ],
  "deferred": false
}
```

`deferred: true` means no tool was confident enough — the message goes to the LLM.

### Rebuild the index

```bash
curl -X POST http://localhost:8000/api/tools/reindex
```

Call this after editing `routing.jsonl` without restarting the server.

### Health check

The `/health` endpoint reports embed model availability:

```json
"embeddings": {
  "model": "karuniaperjuangan/multilingual-e5-small",
  "available": true,
  "backend": "auto",
  "enabled": true
}
```

## Evaluation

Run the eval script to measure accuracy against the labeled set in `data/eval/tool_routing.jsonl`:

```bash
# Token backend (no Ollama needed — CI-safe)
python scripts/eval_tool_routing.py --backend token --show-errors

# Embedding backend
python scripts/eval_tool_routing.py --backend embedding --show-errors

# Rerank backend (requires Ollama + fastembed)
python scripts/eval_tool_routing.py --backend rerank --show-errors

# Hard held-out set (out-of-vocab phrasing — best measured with rerank)
python scripts/eval_tool_routing.py --backend rerank --hard --show-errors

# Fail if accuracy < 90%
python scripts/eval_tool_routing.py --backend token --min-accuracy 0.90 --exit-nonzero
```

Target accuracy: **≥ 94%** on token backend (standard set), **≥ 95%** on hard set with token backend at threshold 0.65, **≥ 97%** with rerank backend.

Note: all deferrals (router not confident) are benign — they fall through to the LLM router and full tool loop.  Precision (no wrong-tool fires) is more important than recall.

### Full benchmark (compare all backends)

```bash
python scripts/benchmark_tool_routing.py
```

Prints accuracy, stage-1 recall, deferral rate, and p50/p95 latency per backend across standard and hard eval sets. Skips backends whose dependencies (Ollama, fastembed) are unavailable.

## Tuning thresholds

If too many messages are misrouted:
1. Run `POST /api/tools/classify` on failing messages and check `top_n` scores.
2. Lower `TOOL_ROUTER_THRESHOLD` (e.g. `0.60`) or `TOOL_ROUTER_MARGIN` (e.g. `0.05`).
3. Add more examples to `routing.jsonl` for confusing pairs.
4. Re-run eval script to confirm improvement.

If the router is overriding the LLM too aggressively:
1. Raise `TOOL_ROUTER_THRESHOLD` (e.g. `0.85`).
2. Remove ambiguous examples from `routing.jsonl`.

## Extending the corpus

Good examples to add:
- **Negative (`tool:"none"`) examples** — advice questions that must NOT fire a tool (highest value for preventing misroutes)
  - `"How can I help Ali feel less overwhelmed?"` → `none`
  - `"What is a good coaching technique for procrastination?"` → `none`
- **Confusable pairs** — minimal-pair examples that share words but map to different tools:
  - `"Ali's age is 23"` → `create_client` vs `"Note that Ali is 23 years old"` → `add_client_note`
  - `"Show me Ali's profile"` → `get_client` vs `"Show me everything about Ali"` → `get_client_full`
- **Multi-clause / noisy real phrasing** — how coaches actually type, not textbook sentences
  - `"ok so Ali just told me his new number is 0912…, save it"` → `create_client`
- **More client names** — add Reza, Dara, Hassan, Maryam, Nadia, Cyrus, Farid beyond Ali/Sara/Mohammad
- **Paraphrases** of existing examples in other phrasing styles

Keep `routing.jsonl` and `data/eval/tool_routing.jsonl` in sync: add eval examples for any new training pattern you add.

For out-of-vocabulary phrasings that test generalization (synonyms, unusual verbs, non-domain vocabulary), add them **only** to `data/eval/tool_routing_hard.jsonl` — not to `routing.jsonl`. This preserves the hard set as a true held-out measure of the embed+rerank layer's generalization.

## Response Formatting (post-routing)

After the fast path executes a tool and returns the raw result, an **optional LLM formatting pass** can rephrase the data into natural, human-friendly text.

```
execute_tool() → raw result
      │
      ▼
is_formattable(reply)?  (only successful read results qualify)
      │ yes
      ▼
format_data_reply()  ← compact LLM call with focused prompt
      │
      ▼
PII validation  →  fallback to deterministic template on failure
      │
      ▼
human-friendly reply
```

This sits **outside** the routing pipeline — routing, tool selection, and parameter extraction remain fully deterministic. The LLM only decides how to present data that has already been fetched.

Enable with:

```env
RESPONSE_FORMATTER_ENABLED=true
```

Benchmark before enabling to measure latency overhead:

```bash
python scripts/benchmark_response_formatter.py
```

See [ADR-0010](adr/0010-llm-response-formatter.md) for the full design and trade-offs.
