# Tool Routing

## What it is

The tool router classifies a coach message into the best-matching tool *before* it reaches the LLM, using example-based similarity. This fixes the most common misrouting error: messages like **"Ali's age is 23"** being sent to `add_client_note` (inserts a new row every time) instead of `create_client` (merges profile fields).

## Routing pipeline

```
User message
  │
  ├─ Pending write confirmation? ────────────────────────── ConfirmOrCancel
  │
  ├─ Regex: profile fields, create/list patterns ─────────── execute_tool directly
  │
  ├─ Tool Router (embedding + token) ─────────────────────── classify_tool()
  │     └─ param extractor ──────────────────────────────── execute_tool or defer
  │
  ├─ Regex + Intent KB (read-only queries) ───────────────── execute_tool or defer
  │
  └─ LLM tool calling ─────────────────────────────────────── last resort
```

**Key principle:** the router picks the *tool*; existing regex helpers extract *parameters*. If a tool is identified confidently but parameters cannot be parsed, the message falls through to the LLM — behavior is unchanged.

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

Each `.md` explains **Use when** / **Do NOT use when** for that tool, with Farsi examples included for multilingual coaches.

### routing.jsonl format

One JSON object per line:

```json
{"utterance": "Ali's age is 23", "tool": "create_client", "hint": "profile:age"}
{"utterance": "Note that Ali decided to change careers", "tool": "add_client_note", "hint": "note_type:decision"}
{"utterance": "What are Ali's goals?", "tool": "list_client_notes", "hint": "note_type:goal"}
```

Fields:
- `utterance` — example coach message (required)
- `tool` — correct tool name (required)
- `hint` — optional metadata, e.g. `"profile:age"`, `"note_type:goal"` — used by param extraction

To add examples, edit `routing.jsonl` and call `POST /api/tools/reindex` (no restart required).

## Backends

| Backend | How it works | When to use |
|---------|-------------|-------------|
| `token` | Token-frequency cosine similarity (same math as RAG retriever) | Always available; CI default; no Ollama needed |
| `embedding` | Dense cosine over Ollama-generated vectors | More accurate for paraphrases and multilingual text; requires embed model |
| `auto` | Probes Ollama at startup; uses `embedding` if available, else `token` | **Recommended default** |

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

### 2. Configure (optional overrides in `.env`)

```env
TOOL_ROUTER_ENABLED=true
TOOL_ROUTER_BACKEND=auto
OLLAMA_EMBED_MODEL=karuniaperjuangan/multilingual-e5-small
TOOL_KNOWLEDGE_DIR=docs/tool-knowledge
TOOL_ROUTER_THRESHOLD=0.75
TOOL_ROUTER_MARGIN=0.08
TOOL_ROUTER_USE_E5_PREFIX=true
```

Docker users: the embed model must be pulled on the **host** Ollama. The API reaches it via `host.docker.internal:11434`. The `docs/tool-knowledge/` directory is mounted read-only into the container.

### 3. E5 prefix convention

`multilingual-e5-small` requires specific prefixes for best accuracy:
- User messages indexed as **passages**: `"passage: {text}"`
- Query at classify time: `"query: {text}"`

Set `TOOL_ROUTER_USE_E5_PREFIX=false` when using a model that does not expect these prefixes.

> The corpus is English-only. `multilingual-e5-small` is still the recommended model because it handles diverse English phrasing well and can be extended with other languages later simply by adding examples to `routing.jsonl`.

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

# Compare and fail if accuracy < 90%
python scripts/eval_tool_routing.py --backend token --min-accuracy 0.90 --exit-nonzero
```

Target accuracy: **≥ 90%** on token backend, **≥ 92%** on embedding backend.

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
- **Hard negatives** — same subject, different tool (most valuable for disambiguation)
  - `"Ali's age is 23"` → `create_client` vs `"Note that Ali is 23"` → `add_client_note`
- **Paraphrases** of existing examples in other phrasing styles
- **Farsi/Persian** variants of high-frequency commands

Keep `routing.jsonl` and `data/eval/tool_routing.jsonl` in sync: add eval examples for any new training pattern you add.
