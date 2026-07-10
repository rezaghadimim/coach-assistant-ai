# Cross-file contracts (must-match registry)

Before changing any value in the tables below, update **every** listed location in the same commit, then run `scripts/check_contracts.py` (once T-020 lands).

Verified 2026-07-10 against source. Centralization of these values is scheduled: magic strings → T-030; tool-name lists → T-031.

---

## 1. Magic strings

| Value | Locations | Role | Drift breaks |
|-------|-----------|------|--------------|
| `"Here are the details on file:\n\n"` | Producer: `app/core/llm.py:249` (`_format_direct_lookup_reply`). Consumer constant: `app/core/response_formatter.py:31` (`_DATA_REPLY_PREFIX`); gate: `is_formattable` uses it | Prefix on successful data-reply templates | Formatter never treats replies as formattable → all data-reply formatting silently disabled |
| `"No notes on file."` | Producer: `app/core/tools.py:175`. Matcher: `app/core/llm.py:144` (`_notes_grounded`, guardrail E) | Empty-notes sentinel | Guardrail E stops firing or fires incorrectly |
| `"Registered clients:"` | Producer: `app/core/tools.py:621`. Matchers: `app/core/response_formatter.py:137`, `:281` | `list_clients` reply header | Deterministic client-list table formatting skipped |
| `"pending confirmation"` | Producers: `app/core/tools.py:148`, `:161`, `:199` (also related preview copy at `:217`, `:229`). Matcher: `app/core/confirmations.py:167` | Marks write-preview text so confirm/cancel can find the pending write | Confirmation replay fails to bind to the preview |
| Emoji `⏳` / `✅` / `❌` | Producers throughout `app/core/tools.py` execute paths (e.g. `:148`, `:528`, `:539`). Semantics documented in `ToolOutcome` docstring `:16-33` and `docs/CONVENTIONS.md` | User-facing status markers tied to `preview` / `ok` / `error` | Coaches (and formatters that key off prefixes) misread write vs error vs success |

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
