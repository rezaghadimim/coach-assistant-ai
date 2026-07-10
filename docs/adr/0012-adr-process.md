# ADR-0012: ADR process

**Date:** 2026-07-10
**Status:** Accepted

## Context

`docs/adr/` has a template and an index, but no written process for when an ADR is required, how numbers are assigned, or how supersession is recorded. Without that, contributors (including AI sessions) either skip ADRs for architecture-affecting changes or write them for trivia, and supersession stays ad-hoc prose in Status lines.

## Decision

1. **When an ADR is required.** Write an ADR before (or as part of) any change to:
   - module boundaries / layering,
   - storage schema mechanics (migrations, PRAGMA policy, which store owns which tables),
   - provider or backend selection (LLM, embed, rerank, tool-router backends),
   - external wire formats (OpenAI-compat envelopes, SSE framing),
   - cross-file contracts registered in `docs/CONTRACTS.md` (once that file exists).

   An ADR is **not** required for bug fixes, documentation-only edits, tests, or single-module refactors that do not change the above.

2. **Numbering.** Use the next free 4-digit number (`ls docs/adr/` first). Never renumber existing ADRs. Filename: `NNNN-short-slug.md`.

3. **Supersession.** When a new ADR replaces an old one:
   - Old ADR: set `**Status:** Superseded by ADR-NNNN` (keep the body intact).
   - New ADR: name what it supersedes in **Context**.

4. **Format.** Every ADR uses the template in `docs/adr/README.md`: Date (real calendar date), Status, Context, Decision, Consequences, and Alternatives Considered when useful.

## Consequences

- Architecture-affecting roadmap tasks can point at a named ADR in their "ADR impact" field.
- Reviewers have a binary check: does this PR touch a contract/boundary without an ADR?
- Historical ADRs 0001–0005 may carry backfilled dates; new ADRs must use real dates.

## Alternatives Considered

- **ADRs for every non-trivial PR** — rejected; noise would bury real decisions.
- **RFC/PR description only** — rejected; decisions need a stable, linkable home outside git history archaeology.
