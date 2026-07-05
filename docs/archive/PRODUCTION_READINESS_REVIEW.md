> **ARCHIVED 2026-07-05** — point-in-time audit (2026-07-04) that motivated the
> production-readiness hardening; findings were addressed via the
> [checklist](PRODUCTION_READINESS_CHECKLIST.md). Lasting guidance lives in
> [docs/OPERATIONS.md](../OPERATIONS.md).

# Production-Grade Engineering Review — Coach Assistant AI

> **Type:** Point-in-time engineering audit (read-only; no code was changed).
> **Date:** 2026-07-04
> **Scope:** Whole codebase (~29k LOC). Judged on engineering quality, not scale.
> **Companion doc:** [PRODUCTION_READINESS_CHECKLIST.md](./PRODUCTION_READINESS_CHECKLIST.md) — the actionable, trackable task list derived from this review.

---

## Executive Summary

This is an **ambitious, unusually thoughtful AI system wrapped in an application that is not yet safe to put in front of real users.** The AI layer shows senior-level design instinct — a layered tool router (token → embedding → cross-encoder → constrained-JSON LLM), per-task temperatures, deterministic anti-hallucination guardrails with PII-preservation checks, two-phase RAG, and verbatim expert-idea attribution that structurally cannot be fabricated. There is a real test suite (515 tests), real observability (correlation IDs, step logs), real ADRs, and graceful backend-degradation everywhere.

The same system has **zero authentication on endpoints that store and return client PII**, a **cross-tenant IDOR** on note update/delete, **prompt-injection-writable** system-prompt content, an **SSRF / argument-injection path through `yt-dlp`**, path traversal via an unvalidated `source_id`, and it **ships to Docker running `uvicorn --reload` as root**. Separately, the AI cleverness is bought with very high complexity: a large parallel regex-based "shadow NLP" layer (≈80 compiled patterns in `app/core`), control flow encoded in emoji string-prefixes (`⏳`/`✅`/`❌`), and a confirmation flow that re-parses its own rendered preview text.

**Verdict up front: not production-ready, primarily on security, secondarily on deployment configuration.** The engineering *intent* is ~7/10; *production trustworthiness* is held to ~5/10 by security and ops gaps. None of the blocking issues are architectural dead-ends — they are omissions.

**Correction for the record:** a common auto-scan claim that `MemoryStore.update_client_note` (the f-string `UPDATE`) is SQL-injectable is a **false positive** — the interpolated fragments are hard-coded literals (`"title = ?"`, `"note_type = ?"`) and all values are bound parameters (`app/memory/store.py:341`). It is safe.

---

## Strengths (with evidence)

1. **The AI routing/grounding design is genuinely strong.** Cascade in `app/core/tool_router.py:540` (rerank → embedding → token → defer) with per-stage threshold + cross-tool margin gates, backed by a constrained-JSON LLM fallback using Ollama's `format` schema (`app/core/llm_router.py:106`). Each stage degrades gracefully and is observable.
2. **Anti-hallucination is a first-class engineering concern, not a prompt.** Deterministic guards in `app/core/llm.py:149` (`_ground_data_reply`), `app/core/llm.py:116` (`_references_unknown_client`), and a PII-preservation check (`app/core/response_formatter.py:330`) mechanically replace fabricated PII/notes with the real record. Expert-idea attributions are built verbatim from retrieval (`app/api/chat.py:81`). **Fully unit-tested** (`tests/test_llm_guardrails.py`, guards A–E).
3. **Per-task temperature discipline** — `temperature_tool=0.0`, `temperature_grounded=0.0`, `temperature_advice=0.5` (`app/core/config.py:51`).
4. **Observability is real and usable** — correlation-ID context vars, greppable single-line step logs with a fixed outcome vocabulary (`app/core/observability.py:146`), a `/health` that reports per-layer *degradation* (`main.py:132`), thread-safe routing stats (`app/core/routing_observability.py:32`).
5. **Test breadth is respectable** — 515 test functions across 41 files, 29 use mocking, provider failures simulated, write-confirmation flow exercised. ADRs document real decisions.
6. **Clean provider/embedding abstraction and config hygiene** — pluggable providers, Pydantic settings with legacy-alias migration (`app/core/config.py:224`), correct secret handling (`.env` and `*.db` gitignored, no secrets logged).

---

## Weaknesses (most critical first, with evidence + impact)

- **No authentication/authorization anywhere.** No `Depends`/`Security`/API-key/bearer in the codebase. Every endpoint trusts a caller-supplied `user_id` (`app/api/chat.py:115`, `app/api/users.py:33`). Anyone reaching the port reads/writes/deletes all data.
- **Cross-tenant IDOR on notes.** `PUT`/`DELETE /clients/{user_id}/notes/{note_id}` (`app/api/users.py:97`, `:117`) pass `note_id` straight to the store; `{user_id}` is never checked against the note owner (`app/memory/store.py:332`, `:438`).
- **Stored content injected into the system prompt unescaped.** Notes + last summary are concatenated into the system prompt (`app/api/chat.py:63`–76). Notes are writable without auth → injected instructions execute on the coach's next turn.
- **SSRF + `yt-dlp` argument-injection + arbitrary local-file read via unauthenticated ingest.** `source["uri"]` → `subprocess.run(["yt-dlp", …, url])` (`app/knowledge/jobs.py:95`); a URI starting with `-` is parsed as an option. `local_media` uses `Path(source["uri"])` (`app/knowledge/jobs.py:68`). *Mitigation:* list-form subprocess (no shell), no `eval`/`pickle`.
- **Path traversal via `source_id`.** No validation (`app/models/schemas.py:275`); used as a directory segment then `mkdir`/`write_text` (`app/api/collections.py:108`). (`slug` is validated `^[a-z0-9-]+$`; `source_id` is not.)
- **Ships in development mode to production.** `Dockerfile:18` → `uvicorn.run(..., reload=True)` (`main.py:230`); container **runs as root** (no `USER`); no image `HEALTHCHECK`; `/docs` + `/openapi.json` exposed.
- **Summarizer runs a full LLM call on the request critical path — repeatedly.** `maybe_update_summary` gates only on `count >= threshold` with **no "already-summarized" marker** (`app/memory/session.py:60`), awaited inline (`app/api/chat.py:168`, `app/api/openai_compat.py:409`). From message 20 onward, **every** turn re-summarizes (up to `ollama_timeout=120s`) before replying.
- **High complexity / hidden coupling in the "shadow NLP" layer.** `client_intents.py` alone: ~30 regexes + 15 `detect_/is_/try_` helpers (≈80 `re.compile` across `app/core`). Control flow threaded through emoji string-prefixes checked in ≥4 modules. Adding one tool touches ~7 files (shotgun surgery).
- **Confirmation safety depends on re-parsing rendered UI text.** `parse_pending_write` regexes the assistant's own preview strings back into tool args (`app/core/confirmations.py:86`). Preview wording changes silently break confirm-to-save.
- **Async correctness gaps (mostly latent under the single-worker default).** Sync SQLite on the event loop (~10–12 calls/request, `app/api/chat.py:128`); no WAL/`busy_timeout` (`app/memory/store.py:20`); new `httpx.AsyncClient` per LLM call (`app/core/llm_providers/ollama.py:70`); no retries; no per-request deadline; streaming persists after client disconnect (`app/api/openai_compat.py:231`). The session/index races are **real only with multiple workers/threads** — the default single event loop makes those sync sections atomic — but they are unguarded landmines once workers are added. ("FD exhaustion from unclosed connections" is **overstated**: CPython closes on refcount drop at function return.)

---

## Top 10 Critical Issues

| # | Severity | Issue | Evidence |
|---|----------|-------|----------|
| 1 | Critical | No authentication/authorization on any endpoint | `main.py:103-109`, `app/api/*` |
| 2 | Critical | Cross-tenant IDOR on note update/delete | `app/api/users.py:97,117`; `app/memory/store.py:332,438` |
| 3 | High | Prompt injection via stored notes/summaries | `app/api/chat.py:63-77` |
| 4 | High | SSRF + `yt-dlp` arg-injection + local file read | `app/knowledge/jobs.py:68,95-107`; `app/api/collections.py:92` |
| 5 | High | Path traversal via unvalidated `source_id` | `app/models/schemas.py:275`; `app/api/collections.py:108` |
| 6 | Critical (ops) | Prod runs `uvicorn --reload` as root | `Dockerfile:18`; `main.py:230` |
| 7 | High | Summarizer LLM call inline + re-runs every message past threshold | `app/memory/session.py:60`; `app/api/chat.py:168` |
| 8 | High | Confirmation safety coupled to rendered preview text | `app/core/confirmations.py:86`; `app/core/tools.py:114+` |
| 9 | Med→High | Blocking SQLite + no WAL/busy_timeout; latent concurrency races | `app/api/chat.py:128`; `app/memory/store.py:20`; `app/core/tool_router.py:380` |
| 10 | Medium | No auth/security/concurrency/loop-exhaustion tests; no coverage gate | `.github/workflows/tests.yml:28`; `app/core/llm.py:631` |

Full task detail, verification criteria, and agent-assignment prompts are in [PRODUCTION_READINESS_CHECKLIST.md](./PRODUCTION_READINESS_CHECKLIST.md).

---

## Scores (1–10, conservative)

| Category | Score | Justification |
|---|---|---|
| Architecture | 6 | Clean layers + ADRs + provider abstraction; undercut by module-singleton coupling and a duplicative shadow-NLP layer. |
| AI System Design | 6 | Sophisticated routing/grounding/attribution; fragile execution (regex intent, emoji-prefix control flow) and injection exposure. |
| Code Quality | 6 | Readable, typed, documented; 600–800-line modules, string-sentinel control flow, primitive obsession. |
| Backend Engineering | 5 | Solid FastAPI/Pydantic/health; no auth, no input limits, blocking DB in async, IDOR. |
| Reliability | 5 | Excellent degradation/fallbacks; no retries, no request deadline, summarizer on hot path, no WAL/timeout. |
| Performance | 5 | Good caching; per-request httpx clients, repeated inline summarization, sequential multi-LLM hops. |
| Security | 3 | No authn/authz, IDOR, prompt injection, SSRF/traversal on a PII-bearing system. `.env`/subprocess hygiene keeps it off 2. |
| Testing | 6 | 515 tests, guardrails/tools/router well covered; no coverage gate, no authz/concurrency/loop tests, shared DB file. |
| Maintainability | 5 | Strong docs; high change-amplification (a new tool touches ~7 files), preview-text coupling. |
| DevOps | 4 | Thoughtful compose + health endpoints; reload-as-root image, unpinned pip deps, no CI lint/type/coverage, inline unversioned migration. |
| **Overall Engineering** | **5** | High-craft AI core in an app unshippable on security and deploy config. Fixable, not fundamental. |

---

## Final Verdict

- **Production-ready for a small serious product?** **No** — unauthenticated PII access, cross-tenant IDOR, injectable system prompts, SSRF, and dev-reload-as-root deployment. Any one of the first two is disqualifying.
- **Trust it in real usage today?** **No** on any reachable network. On a trusted single-operator LAN with no untrusted callers, it functions well.
- **Maintain it long-term?** **Cautiously yes** — good bones (layering, tests, observability, ADRs), but collapse the shadow-NLP/emoji-sentinel machinery and preview-reparse confirmation before adding features.
- **Biggest risks now:** (1) unauthenticated PII + IDOR; (2) prompt injection via stored notes; (3) SSRF/traversal via ingest; (4) dev-mode/root deployment; (5) evolution cost of the duplicative deterministic layer.
- **Fix before adding features:** Checklist items SEC-01…SEC-06 and OPS-01 (auth, IDOR, injection fencing, ingest validation, traversal, prod entrypoint).

---

## Evidence quality note

Every `file:line` reference was read directly during the review. Four parallel evidence sweeps (security, DevOps, async/reliability, testing) were cross-checked against those reads. Three auto-scan claims were rejected/adjusted: the "SQL injection in `update_client_note`" claim (false positive — parameterized), the "file-descriptor exhaustion" claim (CPython closes on GC), and the session/index concurrency races (reclassified as *latent* — active only under multi-worker/thread deployment, which is not the current default).
