# Cross-file contracts (must-match registry)

Before changing any value in the tables below, update **every** listed location in the same commit, then run `scripts/check_contracts.py` (also runs in CI, `.github/workflows/tests.yml`).

Verified 2026-07-13 against source. Tool-name list centralization is scheduled in T-031.

---

## 1. Magic strings

Authoritative definitions: `app/core/reply_markers.py` (imported by every producer/consumer below).

| Value | Constant | Locations | Role | Drift breaks |
|-------|----------|-----------|------|--------------|
| `"Here are the details on file:\n\n"` | `DATA_REPLY_PREFIX` | Producer: `app/core/llm.py` (`_format_direct_lookup_reply`). Consumer alias: `app/core/response_formatter.py` (`_DATA_REPLY_PREFIX`); gate: `is_formattable` uses it | Prefix on successful data-reply templates | Formatter never treats replies as formattable → all data-reply formatting silently disabled |
| `"No notes on file."` | `NO_NOTES_REPLY` | Producer: `app/core/tools.py` (`_format_client_notes`). Matcher: `app/core/llm.py` (`_notes_grounded`, guardrail E) | Empty-notes sentinel | Guardrail E stops firing or fires incorrectly |
| `"Registered clients:"` | `REGISTERED_CLIENTS_PREFIX` | Producer: `app/core/tools.py` (`list_clients`). Matchers: `app/core/response_formatter.py` (`_format_registered_clients_table`, `_format_compact_client_list`) | `list_clients` reply header | Deterministic client-list table formatting skipped |
| `"pending confirmation"` | `PENDING_CONFIRMATION_MARKER` | Producers: `app/core/tools.py` write-preview formatters. Matcher: `app/core/confirmations.py` (`_lookup_pending_write_from_messages`) | Marks write-preview text so confirm/cancel can find the pending write | Confirmation replay fails to bind to the preview |
| Emoji `⏳` / `✅` / `❌` | — | Producers throughout `app/core/tools.py` execute paths. Semantics documented in `ToolOutcome` docstring and `docs/CONVENTIONS.md` | User-facing status markers tied to `preview` / `ok` / `error` | Coaches (and formatters that key off prefixes) misread write vs error vs success |

---

## 2. Tool names (9)

Authoritative list: `TOOL_DEFINITIONS` in `app/core/tools.py:237` —

`create_client`, `add_client_note`, `get_client`, `get_client_full`, `list_client_notes`, `list_clients`, `update_client_note`, `delete_client_note`, `delete_client`.

| Location | Kind | Notes |
|----------|------|-------|
| `app/core/tools.py:237` `TOOL_DEFINITIONS` | **Source of truth** | Schemas + descriptions for the LLM |
| `app/core/tools.py:53` `_WRITE_TOOLS` | Hand list | Write/confirm tools. Includes `update_client` (alias, not a `TOOL_DEFINITIONS` name) — keep in sync when adding writes |
| `app/core/llm_router.py:35` `_KNOWN_TOOLS` | Hand list | Must equal the 9 `TOOL_DEFINITIONS` names |
| `app/core/llm_router.py:106` `_ROUTER_SCHEMA` | JSON-schema enum | Must list the same 9 names (+ `"none"`) |
| `data/tool-knowledge/*.md` | Tool cards | One markdown card per tool (9 files present) |
| `data/tool-knowledge/examples/routing.jsonl` | Routing corpus | Each example's `tool` field must be one of the 9 (or abstention conventions used by eval) |

Adding a tool requires updating all of the above in one commit (plus routing examples / eval sets as needed).

---

## 3. Other enums

| Enum | Values | Locations | Drift breaks |
|------|--------|-----------|--------------|
| Note types | `general`, `story`, `decision`, `goal`, `progress` | `app/core/tools.py:52` `_VALID_NOTE_TYPES`; inline schema enums at `tools.py:313`, `:393`, `:425` | Invalid note_type accepted/rejected inconsistently; LLM schema disagrees with executor |
| `CorpusKind` | `framework`, `collection` | `app/rag/retriever.py:35`; `app/rag/ingest.py:21`; `app/core/embed_providers/types.py:9` | Wrong index / embed profile selected |
| `ChunkRole` | `general`, `problem`, `solution` | `app/rag/ingest.py:22` (and uses in same module) | Role inference / chunk metadata mismatch. **Not** redefined in `embed_providers/types.py` (only `CorpusKind` is) |
