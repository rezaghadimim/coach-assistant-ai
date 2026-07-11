# AI-Execution Roadmap

**Objective:** make every future implementation session on this repository reliable when executed by a small language model (7B–8B, limited context, no memory of prior sessions).
**Optimizes for:** hallucination resistance, not speed.
**Companion documents:** [REPO_AUDIT.md](REPO_AUDIT.md) (verified facts, risk register R-xx, unknowns U-xx) · [TASK_TEMPLATE.md](TASK_TEMPLATE.md) · [STATUS.md](STATUS.md) (progress ledger) · `tasks/` (one file per task).

---

## 1. Execution protocol (binding rules for every session)

An implementing model MUST follow these rules. They override any instinct to be helpful beyond the task.

1. **One task per session.** Read `docs/roadmap/STATUS.md`, pick the first task whose status is `TODO` and whose dependencies are all `DONE`. Open only that task file.
2. **Read only the files the task lists.** Never load the whole repository. If a listed file:line no longer matches, STOP and record the mismatch in STATUS.md — do not improvise.
3. **Modify only files in "Files allowed to change".** Everything else is forbidden, even for "obvious" fixes. Out-of-scope problems go into STATUS.md under *Notes*, not into the diff.
4. **Verify preconditions before editing.** Every task lists executable precondition checks (grep/test commands). If any check fails, STOP — the repo is not in the expected state.
5. **Never invent an API.** If you need a function/constant/env var not shown in the files you read, check `docs/CONTRACTS.md` and `docs/MODULE_MAP.md` (after T-012/T-013 exist). If still unresolved, STOP and record it as `Unknown`.
6. **Separate facts from assumptions.** Anything not verified from a file you actually read this session is an assumption; write it down as such. Unknowns are marked `Unknown`, never guessed.
7. **Validate with the exact commands in the task.** A task is not done until the full validation block passes.
8. **Stop on uncertainty.** Ambiguity, failing precondition, unexpected diff, unexpected test failure not caused by your change ⇒ revert to clean state (`git checkout -- .`), record findings in STATUS.md, end the session.
9. **One commit per task**, message `T-xxx: <task title>`. This makes every task reversible with a single `git revert`.
10. **Close the loop.** After validation passes: update STATUS.md (status, commit sha, date, notes), and apply the task's "Documentation updates" — in the same commit.

### Standard validation block

Used by every task unless the task overrides it. Run from the repo root (use `python3` if `.venv` is absent):

```bash
.venv/bin/ruff check .
.venv/bin/python -m mypy app/
RAG_BACKEND=token TOOL_ROUTER_BACKEND=token RESPONSE_FORMATTER_ENABLED=false \
  .venv/bin/python -m pytest tests/ -q
```

Facts to know (see REPO_AUDIT.md §4): CI runs Python 3.11; tests hang on Ollama without the env pins; `unittest discover` must never be used (skips `conftest.py`).

---

## 2. Design rationale

Phases are ordered so that **documentation and executable guardrails land before any code moves**:

- **Phase 0 — Ground truth.** Docs currently state false facts (R-01, R-02). A small model trusts docs; false docs are a hallucination generator. Fix them first, cheaply.
- **Phase 1 — AI-execution infrastructure.** Create the small set of documents a model reads *instead of* the repository: root `CLAUDE.md`, conventions, cross-file contracts, module map, wire formats, config reference, dev guide, ADR process.
- **Phase 2 — Executable guardrails.** Turn the contracts into CI checks so drift is caught by a machine, not by a reviewer's memory.
- **Phase 3 — Structural de-risking.** Only now touch code: deduplicate the string/enum/pipeline duplication that forces multi-file synchronized edits, and split the files too large for an 8B context window. Each refactor is one seam, behavior-preserving, test-guarded.
- **Phase 4 — CI hardening.** Align the Python version story and strengthen static gates on the hot files.

Every task is atomic, single-commit, revertible, and references only *completed* predecessors. Total context per task (task file + files to read) is budgeted to stay well under a small model's window (target ≤ ~1,500 lines of input).

---

## 3. Task index

Complexity: S (< 30 min, trivial diff) · M (single focused change) · L (multi-file but mechanical). No task is larger than L by design.

### Phase 0 — Ground truth (no behavior change)

| ID | Title | Risks | Deps | Cx |
|----|-------|-------|------|----|
| [T-001](tasks/T-001-remove-junk-files.md) | Remove tracked junk files | R-19 | — | S |
| [T-002](tasks/T-002-fix-gitmodules-name.md) | Fix `.gitmodules` submodule name | R-02 | — | S |
| [T-003](tasks/T-003-fix-pyproject-pointer.md) | Fix stale doc pointer in pyproject.toml | R-02 | — | S |
| [T-004](tasks/T-004-fix-architecture-doc.md) | Correct stale facts in ARCHITECTURE.md | R-01 | — | S |
| [T-005](tasks/T-005-fix-memory-doc.md) | Correct tool table in MEMORY.md | R-01 | — | S |
| [T-006](tasks/T-006-fix-implementation-doc.md) | Correct IMPLEMENTATION.md and mark it historical | R-01 | — | S |
| [T-007](tasks/T-007-annotate-adr-dates.md) | Annotate backfilled ADR dates | R-02 | — | S |

### Phase 1 — AI-execution infrastructure (documentation)

| ID | Title | Risks | Deps | Cx |
|----|-------|-------|------|----|
| [T-010](tasks/T-010-create-claude-md.md) | Create root CLAUDE.md (AI contract) | R-17, R-18 | — | M |
| [T-011](tasks/T-011-create-conventions-doc.md) | Create docs/CONVENTIONS.md | R-17 | — | M |
| [T-012](tasks/T-012-create-contracts-doc.md) | Create docs/CONTRACTS.md (must-match registry) | R-05, R-06 | — | M |
| [T-013](tasks/T-013-create-module-map.md) | Create docs/MODULE_MAP.md (layering + import rules) | R-07, R-10, R-11, R-16 | — | M |
| [T-014](tasks/T-014-create-wire-formats-doc.md) | Create docs/WIRE_FORMATS.md (OpenAI-compat contract) | R-15 | — | M |
| [T-015](tasks/T-015-adr-process.md) | ADR-0012: define the ADR process | R-17 | — | S |
| [T-016](tasks/T-016-create-config-reference.md) | Create docs/CONFIG.md (env-var reference, audited) | R-20 | — | M |
| [T-017](tasks/T-017-create-development-guide.md) | Create docs/DEVELOPMENT.md (dev/test guide) | R-17, R-18 | T-010 | M |

### Phase 2 — Executable guardrails

| ID | Title | Risks | Deps | Cx |
|----|-------|-------|------|----|
| [T-020](tasks/T-020-contract-check-script.md) | scripts/check_contracts.py + CI step | R-05, R-06 | T-012 | M |
| [T-021](tasks/T-021-doc-path-check-script.md) | scripts/check_doc_paths.py + CI step | R-01, R-02 | T-004, T-005, T-006 | M |

### Phase 3 — Structural de-risking (behavior-preserving)

| ID | Title | Risks | Deps | Cx |
|----|-------|-------|------|----|
| [T-030](tasks/T-030-reply-markers-module.md) | Centralize cross-file reply-marker strings | R-05 | T-012, T-020 | M |
| [T-031](tasks/T-031-single-source-tool-names.md) | Derive tool-name lists from TOOL_DEFINITIONS | R-06 | T-012, T-020 | M |
| [T-032](tasks/T-032-extract-chat-pipeline.md) | Extract shared chat pipeline (used by chat.py) | R-04 | T-013 | L |
| [T-033](tasks/T-033-openai-compat-uses-pipeline.md) | Migrate openai_compat non-streaming path to shared pipeline | R-04 | T-032 | L |
| [T-034](tasks/T-034-knowledgestore-migrations.md) | KnowledgeStore: PRAGMA parity + versioned migrations | R-09 | T-013 | M |
| [T-035](tasks/T-035-move-layer-availability.md) | Move `_layer_availability` out of main.py | R-10 | T-013 | M |
| [T-036](tasks/T-036-remove-dead-embed-cache.md) | Resolve U-02/U-03: dead `embed_collection_chunks` + write-only chunks | R-13 | T-013 | M |
| [T-037](tasks/T-037-public-tokenizer-api.md) | Public tokenizer/cosine API; end cross-module `_private` imports | R-11, R-12 | T-013 | M |
| [T-038](tasks/T-038-extract-embed-cache-io.md) | Split retriever.py: extract embedding-cache I/O | R-08 | T-037 | L |
| [T-039](tasks/T-039-extract-citation-formatting.md) | Split retriever.py: extract citation/prompt formatting | R-08 | T-038 | L |
| [T-040](tasks/T-040-mypy-model-registry.md) | mypy: un-ignore app.core.model_registry (repeatable recipe) | R-14 | — | M |

### Phase 4 — CI hardening

| ID | Title | Risks | Deps | Cx |
|----|-------|-------|------|----|
| [T-050](tasks/T-050-python-version-adr.md) | ADR-0013 + align the Python version story | R-03 | T-015 | M |

---

## 4. Dependency graph

```
Phase 0:  T-001 T-002 T-003 T-004 T-005 T-006 T-007      (all independent)
Phase 1:  T-010 T-011 T-012 T-013 T-014 T-015 T-016      (all independent)
          T-017 ← T-010
Phase 2:  T-020 ← T-012          T-021 ← T-004,T-005,T-006
Phase 3:  T-030 ← T-012,T-020    T-031 ← T-012,T-020
          T-032 ← T-013          T-033 ← T-032
          T-034 ← T-013          T-035 ← T-013
          T-036 ← T-013          T-037 ← T-013
          T-038 ← T-037          T-039 ← T-038
          T-040 ← (none)
Phase 4:  T-050 ← T-015
```

Any topological order is valid. Recommended order = index order above.

## 5. Continuation protocol (session hand-off)

Sessions share **no memory**. All state lives in three places:

1. **git** — one commit per completed task, message `T-xxx: <title>`.
2. **[STATUS.md](STATUS.md)** — the ledger: per-task status (`TODO` / `IN-PROGRESS` / `DONE` / `BLOCKED`), commit sha, date, notes. A task left `IN-PROGRESS` with no commit means the working tree may be dirty: run `git status`; if dirty, `git checkout -- .` and restart the task from scratch.
3. **Task files** — immutable instructions. If reality has drifted from a task file (precondition fails), the task is `BLOCKED`; a maintainer (or a planning-capable model) revises the task file before anyone retries it.

A fresh session needs to read exactly: this README §1, STATUS.md, and one task file. Nothing else.

## 6. Adding new tasks

New work (features, fixes) must be turned into task files using [TASK_TEMPLATE.md](TASK_TEMPLATE.md) **before** any implementation session runs. Authoring tasks requires repo knowledge — it is a job for a maintainer or a large model, never for the implementing small model. Architecture-affecting tasks must name their ADR in "ADR impact" (process: `docs/adr/README.md`, after T-015).
