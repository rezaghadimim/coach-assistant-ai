# ADR-0010: Optional LLM Formatting Pass for Human-Friendly Data Replies

**Date:** 2026-06-16
**Status:** Accepted

## Context

The fast-path routing stack (regex → tool router → intent KB → LLM router fallback) was designed to execute client data tools without calling the main LLM.  It succeeds at returning accurate, structured data — but the output is mechanical and template-driven:

```
Here are the details on file:

Client ID: ali
Name: Ali Hassan
Email: ali.hassan@example.com
Phone: (not set)
Age: 32
Occupation: Software Engineer
Background: (not set)
```

Root causes of the UX gap:

1. **Template-bound replies** — `_format_direct_lookup_reply` wraps every successful read result in the same static header.  A coach asking "what is Ali's email?" receives a full profile block instead of a single-sentence answer.

2. **No adaptive presentation** — the format is always a flat key-value block regardless of what was asked.  A request like "show all patients in a table" receives a plain bullet list.

3. **Single user, human-facing** — the application is used by one coach whose end clients interact via Open WebUI.  Natural, conversational replies matter more than machine-parseable output.

Two improvements are needed:
- **Present only what was asked** — answer "what is Ali's email?" with one sentence, not a full profile dump.
- **Adapt tone and layout** — "who are my clients?" can receive a compact list or inline names rather than a labeled block.

The constraint is that routing, tool selection, and parameter extraction must remain deterministic.  The LLM should not be trusted to decide *what* data to fetch — only *how* to present data that has already been fetched.

## Decision

### 1. Response Formatter module (`app/core/response_formatter.py`)

A new module with a single public coroutine:

```python
async def format_data_reply(user_message: str, reply: str, provider) -> str
```

It accepts the original coach message and the deterministic template reply (which always starts with `"Here are the details on file:\n\n"`), strips the mechanical prefix, and asks the LLM to rephrase the raw data section concisely.

A focused single-purpose system prompt governs the LLM call:

```
You are a data presentation assistant for a life-coaching app.
Answer ONLY what the coach asked. Use warm, conversational language.
NEVER invent, omit, or paraphrase any contact details.
NEVER add follow-up questions or coaching advice.
Keep the reply short: one to three sentences for profiles; a compact list for multi-client results.
```

The module also exports:

```python
def is_formattable(reply: str) -> bool
```

which returns `True` only when *reply* starts with the deterministic prefix — ensuring write previews (⏳), outcomes (✅/❌), scope refusals, and greetings are never passed to the formatter.

### 2. PII validation and deterministic fallback

After the LLM returns its rephrasing, every email address and phone number extracted from the raw source data is checked against the formatted output.  Specifically:

- `_EMAIL_RE` extracts tokens matching `[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}`
- `_PHONE_RE` extracts tokens matching `\+?[\d][\d\s\-\(\)\.]{5,}\d`

If any token is missing from the formatted reply, or if the LLM call raises an exception, or if the LLM returns an empty string, the **original deterministic reply is returned unchanged**.  The formatter can never make data *worse* — only better.

### 3. Insertion points in the pipeline

The formatter is applied at exactly two points, both already async:

```
fast path returns data reply
        │
        ▼
is_formattable(reply)?
        │ yes                no
        ▼                    ▼
format_data_reply()    return reply as-is
        │
        ▼
PII validation pass?
        │ yes                no / error
        ▼                    ▼
return formatted       return deterministic reply
```

**`app/core/llm.py` — `_generate_with_tools`** (two places):
1. After `try_direct_reply` returns a non-None result (fast-path early return).
2. After `_try_llm_router_action` returns a non-None result (LLM router fallback early return).

**`app/api/chat.py` — `chat` endpoint**:
3. After the `try_direct_reply` early-return branch that bypasses `generate_response`.

### 4. Feature flag and temperature (`app/core/config.py`)

| Key | Default | Purpose |
|-----|---------|---------|
| `RESPONSE_FORMATTER_ENABLED` | `true` | LLM formatting pass for fast-path data replies |
| `TEMPERATURE_GROUNDED` | `0.0` | Temperature used for the formatter LLM call |
| `MAX_TOKENS_CLASSIFY` | `64` | Token budget for the formatter call |

Disable with `RESPONSE_FORMATTER_ENABLED=false` to skip the extra LLM call and return the deterministic template only.  The formatter call always runs at `TEMPERATURE_GROUNDED=0.0` for deterministic output — the global `TEMPERATURE` setting does not apply to it.

### 5. Benchmark script (`scripts/benchmark_response_formatter.py`)

A new script measuring formatter OFF vs ON across a built-in 8-sample eval set of coach data-retrieval messages with known expected PII fields.

Metrics per sample:
- `latency_off_ms` — deterministic template latency (in-process, µs-range)
- `latency_on_ms` — full round-trip with LLM formatter (Ollama network call)
- `pii_preserved` — boolean: expected PII tokens appear verbatim in output
- `char_delta` — formatted length minus deterministic length

CLI:
```bash
python scripts/benchmark_response_formatter.py           # default model, all samples
python scripts/benchmark_response_formatter.py --no-llm  # deterministic baseline only
python scripts/benchmark_response_formatter.py --samples 4 --model llama3.1:8b
```

### 6. Operational decision — enable by default (2026-06-20)

Benchmark run on local hardware with `llama3.1:8b` (`python3 scripts/benchmark_response_formatter.py --samples 8`):

| Metric | Result |
|--------|--------|
| Samples | 8 |
| PII preservation | 100% (8/8) |
| Avg latency OFF | ~0 ms (deterministic template, in-process) |
| Avg latency ON | 686 ms |
| Avg overhead | 686 ms per formatted reply |
| Avg char delta | −106 (formatted replies shorter and more concise) |

**Decision:** Enable the formatter by default (`RESPONSE_FORMATTER_ENABLED=true` / `response_formatter_enabled: true`).  PII validation and deterministic fallback remain the safety net; disable explicitly if latency is unacceptable on your hardware or if a different model fails the benchmark.

## Consequences

**Positive:**
- Coach conversations feel natural and conversational for the application's human end-users.
- Data accuracy is unchanged — the LLM formats what was fetched, not what it guesses.
- PII validation ensures contact details can never be silently dropped by a small model.
- Deterministic fallback guarantees the coach always receives a complete reply even if Ollama is slow or the model returns a poor rephrasing.
- Feature flag allows instant rollback with no code change.
- Zero new dependencies — the existing provider abstraction is reused.
- 19 unit and integration tests cover all code paths including PII drop, LLM error, and the flag.

**Negative:**
- Each formatted fast-path reply adds one LLM round-trip (~500–2000 ms on a local small model; ~686 ms measured on `llama3.1:8b`).
- Small models may occasionally drop or rephrase phone numbers in unusual formats; the `_PHONE_RE` extractor may not catch all variants, so the PII check is not 100% exhaustive.
- Operators on slow hardware or with unreliable models should disable with `RESPONSE_FORMATTER_ENABLED=false` after re-running the benchmark.
- The formatter system prompt is a single shared prompt for all tools.  Unusual tool outputs (e.g. multi-client tables with notes) may produce inconsistent formatting on smaller models.

## Alternatives Considered

| Option | Reason Not Chosen |
|--------|-------------------|
| Always format with LLM (no fast path) | LLM decides both what to fetch and how to present; small models misroute and dead-end without the deterministic pipeline |
| Template engine with field-specific formatters | Requires a separate formatter per tool and per question type; cannot adapt to open-ended phrasing; low maintainability |
| Post-process with a rule-based extractor | Fragile; would need regex per field per question variant; same brittleness as the original template |
| Always use full LLM tool-calling loop | Removes the latency and reliability benefits of the fast path; confirmed to fail for unusual phrasings (see ADR-0009) |
| No formatter (current state) | Accurate but robotic; acceptable for a developer API, not for a coach-facing application |

## Future Direction

- Re-run `scripts/benchmark_response_formatter.py` after changing models or hardware. If PII preservation falls below 98%, disable the formatter or tighten the system prompt.
- Add per-tool formatter prompts when the generic prompt proves too coarse (e.g. a dedicated list-clients formatter that produces a compact table when requested).
- Explore streaming the formatted reply via `provider.stream()` so the coach sees the first words immediately rather than waiting for the full Ollama round-trip.
- When a fine-tuned model is available (Phase 5), evaluate whether it produces better formatting without a separate formatter call.
- Extend `_PHONE_RE` with additional regional formats if the coach's client base includes less-common number conventions.
