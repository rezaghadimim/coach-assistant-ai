# Coding conventions

Verified against the codebase. Prefer matching these over inventing new patterns.

## 1. Result-object twins (`_with_meta`)

Fast-path helpers come in pairs:

- `try_direct_*_with_meta(...)` returns a dataclass / result object (reply + metadata).
- The bare `try_direct_*(...)` twin returns only the string (`.reply`), for legacy callers.

Evidence: `try_direct_reply_with_meta` / `try_direct_reply` (`app/core/llm.py:331`, `:374`);
`try_direct_client_action_with_meta` / `try_direct_client_action` (`app/core/client_intents.py:638`, `:697`);
query twins at `client_intents.py:571`, `:627`.

**New code uses the `_with_meta` form.** Do not add new bare-string-only entry points.

## 2. Tool outcome statuses + emoji markers

`ToolOutcome.status` vocabulary (`app/core/tools.py:12`, `:16-33`):

| `status` | Meaning | Typical `text` prefix |
|----------|---------|------------------------|
| `preview` | Write pending coach confirmation (nothing saved) | `⏳` |
| `ok` | Confirmed write completed | `✅` |
| `error` | Tool could not run | `❌` |
| `info` | Successful read (profile, notes, list) | (no required emoji) |

`status` drives control flow (`is_terminal` for `preview`/`ok`/`error`). Emoji prefixes in `text` are user-facing display only (see usages around `tools.py:148+`).

## 3. Guardrail legend (A / B / C / E — no D)

Letter names used in comments in `app/core/llm.py`:

| Letter | What it blocks | Where |
|--------|----------------|-------|
| **A** | Fabricated PII (email/phone not in stored record) | `_ground_data_reply` + `_pii_preserved` (`llm.py:149-176`) |
| **B** | Same path: replace untrusted free-form text with the real record | `_ground_data_reply` (`llm.py:149-180`) |
| **C** | Lookup naming a client not on file → deterministic abstain before LLM | `_references_unknown_client` (`llm.py:116-134`, call site `:506-515`) |
| **E** | Fabricated note/goal/decision content when none on file | `_notes_grounded` (`llm.py:137-146`) |

There is **no guardrail D** as a lettered check. (Historical docs sometimes labeled a broadened `_is_data_request` as “D”; that is a gate, not a lettered guardrail.)

## 4. “Router” disambiguation

Three different things share the word “router”:

| Name | Role |
|------|------|
| `tool_router` (`app/core/tool_router.py`) | Semantic classify via token / embedding / rerank |
| `llm_router` (`app/core/llm_router.py`) | One constrained LLM JSON call to pick a tool name |
| `_tool_router_action` (in `client_intents`) | Dispatch helper after intent detection — not the embed router |

Do not conflate them in docs or new APIs.

## 5. Settings access

Always:

```python
from app.core.config import settings
```

`settings` is the module singleton (`app/core/config.py:379`). Env var name = uppercased field name. **Do not** read `os.environ` directly in `app/` code (tests/conftest may set env before import).

## 6. In-function imports are deliberate

Many `from app.core... import ...` calls sit inside functions to break import cycles among `llm` ↔ `client_intents` ↔ `tools` ↔ `tool_router` ↔ `response_formatter` ↔ `llm_router`. **Do not lift them to module level** without checking the cycle. Full layering rules: `docs/MODULE_MAP.md` (if missing, roadmap T-013 has not run).

## 7. Test conventions

- Files: `tests/test_<area>.py`.
- Mostly `unittest.TestCase`; bare pytest classes are also accepted.
- No pytest marks for optional live tests — gate on env flags (e.g. `RUN_RERANK_INTEGRATION=1`).
- Run **only** via pytest (never `unittest discover`).
- `tests/conftest.py` sets `DEBUG=true`, a temp `MEMORY_DB_PATH`, full env pins (`tests/isolation_support.py`), and a fail-fast network guard before app imports. Policy: `docs/TEST_EXECUTION.md` (ADR-0014).

## 8. MemoryStore migrations

`MIGRATIONS` in `app/memory/store.py:88-95` is **append-only**. Never reorder or remove entries; each index is the schema version it upgrades *to*.

## 9. Naming debt (do not imitate)

- Cross-module imports of `_underscored` “private” names exist (`_tokenize`, `_tf_cosine`, `_pii_preserved`, …) but are **deprecated** — public APIs land in roadmap T-037.
- Rerank filenames: engine `app/core/rerank.py`; transports `rerank_tei.py` / `rerank_openai_compat.py`; RAG facade `app/rag/reranker.py`. Do not merge these names casually.
