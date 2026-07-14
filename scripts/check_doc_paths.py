"""Check that repo paths referenced in documentation actually exist.

Scans README.md, CLAUDE.md, and docs/**/*.md (excluding docs/archive/ and
docs/roadmap/, which are historical/self-referential) for candidate repo
paths and verifies each one exists on disk.

Usage:
    python scripts/check_doc_paths.py

Prints each missing path; exits non-zero if any are found.
Runs fully offline: it only reads files as text.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Paths the checker cannot resolve confidently; each entry needs a comment
# explaining why (runtime-generated, gitignored, or submodule-only in CI).
KNOWN_UNRESOLVED: dict[str, str] = {
    "data/coach_assistant.db": (
        "SQLite file matched by the *.db gitignore rule; created at runtime, "
        "never committed."
    ),
    "data/rag_index_cache.json": (
        "Explicitly gitignored regenerable cache file (see .gitignore); "
        "created on startup/ingest, never committed."
    ),
    "data/knowledge/private/collections": (
        "Subdirectory inside the data/knowledge/private git submodule "
        "(.gitmodules); CI's actions/checkout does not init submodules, "
        "so this path is absent in CI even though the doc reference is valid."
    ),
}

_TOP_LEVEL_DIRS = ("app", "data", "docs", "scripts", "tests")

# Markdown link targets: [text](path)
_MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")

# Backtick-quoted candidate repo paths, e.g. `app/core/tools.py`
_BACKTICK_PATH_RE = re.compile(
    r"`((?:" + "|".join(_TOP_LEVEL_DIRS) + r")/[A-Za-z0-9_./-]+)`"
)

_URL_PREFIXES = ("http://", "https://", "mailto:")


def candidate_files() -> list[Path]:
    files = []
    for name in ("README.md", "CLAUDE.md"):
        path = REPO_ROOT / name
        if path.exists():
            files.append(path)
    docs_dir = REPO_ROOT / "docs"
    for path in sorted(docs_dir.rglob("*.md")):
        rel = path.relative_to(REPO_ROOT)
        if rel.parts[1:2] == ("archive",) or rel.parts[1:2] == ("roadmap",):
            continue
        files.append(path)
    return files


def _strip_suffix(candidate: str) -> str:
    candidate = candidate.split("#", 1)[0]
    candidate = candidate.split(":", 1)[0]
    return candidate.strip().rstrip("/")


def _is_skippable(candidate: str) -> bool:
    if not candidate:
        return True
    if candidate.startswith(_URL_PREFIXES):
        return True
    if "*" in candidate:
        return True
    if "<" in candidate or ">" in candidate:
        return True
    return False


def extract_candidates(text: str) -> set[str]:
    candidates: set[str] = set()

    for match in _MD_LINK_RE.finditer(text):
        raw = match.group(1).strip()
        if _is_skippable(raw):
            continue
        stripped = _strip_suffix(raw)
        if not stripped:
            continue
        if stripped.startswith(tuple(d + "/" for d in _TOP_LEVEL_DIRS)):
            candidates.add(stripped)

    for match in _BACKTICK_PATH_RE.finditer(text):
        raw = match.group(1).strip()
        if _is_skippable(raw):
            continue
        stripped = _strip_suffix(raw)
        if stripped:
            candidates.add(stripped)

    return candidates


def main() -> int:
    missing: list[tuple[str, str]] = []

    for doc_path in candidate_files():
        rel_doc = doc_path.relative_to(REPO_ROOT)
        text = doc_path.read_text(encoding="utf-8")
        for candidate in sorted(extract_candidates(text)):
            if candidate in KNOWN_UNRESOLVED:
                continue
            if not (REPO_ROOT / candidate).exists():
                missing.append((str(rel_doc), candidate))

    if missing:
        for doc, candidate in missing:
            print(f"MISSING: {candidate} (referenced in {doc})")
        print(f"\n{len(missing)} dead path reference(s) found.")
        return 1

    print("All documented repo paths resolve.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
