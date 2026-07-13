# ADR-0013: Python version policy

**Date:** 2026-07-13
**Status:** Accepted

## Context

Five configuration surfaces disagreed about which Python version the project targets:

| Surface | Value | Role |
|---------|-------|------|
| `.python-version` | 3.12 | Local dev default (pyenv/asdf) |
| `.github/workflows/tests.yml` | 3.11 only | CI test runner |
| `pyproject.toml` `requires-python` | `>=3.11` | Declared install/runtime floor |
| `pyproject.toml` ruff `target-version` | py311 | Lint/syntax ceiling for authored code |
| `pyproject.toml` mypy `python_version` | 3.12 | Type-checker parse target (numpy stubs need 3.12+) |

This split is easy to miss: a contributor on 3.12 can merge syntax or/stdlib usage that passes local checks but fails CI on 3.11, or avoid 3.12-only typing features mypy expects.

## Decision

1. **Runtime floor stays 3.11.** `requires-python = ">=3.11"` and ruff `target-version = "py311"` are unchanged. All application code must run on Python 3.11.
2. **Local default stays 3.12.** `.python-version` remains `3.12` for developer ergonomics; mypy stays on 3.12 to parse numpy's bundled stubs.
3. **CI tests both 3.11 and 3.12.** `.github/workflows/tests.yml` uses a matrix over `["3.11", "3.12"]` with identical steps (lint, contract checks, mypy, pytest + coverage gate per leg).

## Consequences

- Contributors must write code compatible with **3.11** even when developing on 3.12. Ruff's py311 target enforces this for syntax; the 3.11 CI leg catches anything ruff misses.
- CI cost doubles for the test job (two matrix legs). Acceptable for a small suite with the Test Execution Contract (~8s per leg locally).
- mypy may accept constructs that 3.11 rejects only if they are typing-only; runtime code is guarded by the 3.11 CI leg.
- Docker/production images should continue to pin a specific 3.11+ image; this ADR does not mandate 3.12 in production.

## Alternatives Considered

- **Raise floor to 3.12 everywhere** — rejected for now; would break the declared `>=3.11` contract and any 3.11 deployments without a measured benefit.
- **CI 3.11 only, document the split** — rejected; the accidental drift (R-03) stays invisible until someone hits it.
- **CI 3.12 only** — rejected; drops coverage of the declared runtime floor.
