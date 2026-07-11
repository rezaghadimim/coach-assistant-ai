# Task template

Copy this file to `tasks/T-xxx-<slug>.md`. Every field is mandatory — write `None` explicitly rather than omitting a section. Keep the whole file under ~120 lines; if a task needs more, split the task.

Authoring rules:
- Cite evidence as `file:line`. Verify every citation at authoring time; implementing models treat citations as ground truth.
- Preconditions and validation must be **executable commands with expected output**, not prose.
- "Files to read" totals ≤ ~1,200 lines. If the task needs more context, split it or extract the needed facts into the task file itself.
- Anything not verifiable from the repo is written as `Unknown`, with the command or question that resolves it.

---

# T-xxx — <Title (imperative)>

**Phase:** <n> · **Complexity:** S | M | L · **Estimated session:** <total lines of input; expected diff size>
**Risks addressed:** R-xx, … (see ../REPO_AUDIT.md) · **Status:** tracked in ../STATUS.md, not here

## Goal
One or two sentences. What is true after this task that was not true before.

## Why this task exists
The failure mode it prevents, referencing risk IDs.

## Context required
The complete reading list. The implementing model reads nothing else.
- `docs/roadmap/README.md` §1 (protocol)
- this file
- `<file>` lines <a–b> — <why>

## Files allowed to change
Exhaustive list. Creating a file counts as changing it.

## Files forbidden to change
"Everything not listed above" **plus** call out tempting-but-forbidden files explicitly.

## Dependencies
Task IDs that must be `DONE` in STATUS.md first. `None` if independent.

## Preconditions (verify before editing)
```bash
# command                                   # expected result
```
If any check fails: STOP, mark task BLOCKED in STATUS.md, end session.

## Steps
Numbered, mechanical, no design decisions left to the implementer. Any decision point must instead be resolved here, at authoring time.

## Acceptance criteria
Observable, binary statements.

## Required tests
New/updated tests, named. `None (docs-only)` where applicable — docs-only tasks still run the standard validation block.

## Validation (run exactly)
```bash
# usually the standard validation block from ../README.md §1, plus task-specific checks
```

## Documentation updates
Which docs change in this same commit. `None`.

## ADR impact
`None` | `Updates ADR-xxxx` | `Requires new ADR-xxxx (write it as part of this task)`.

## Definition of Done
- All acceptance criteria met; validation block passes.
- Single commit `T-xxx: <title>`; no unrelated hunks in the diff.
- STATUS.md row updated (status DONE, commit sha, date).
- Documentation updates included in the same commit.

## Rollback plan
Usually: `git revert <commit>` — state why that is safe (no data migrations, etc.), or give the specific rollback steps if not.
