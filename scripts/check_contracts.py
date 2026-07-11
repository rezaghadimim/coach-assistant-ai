"""Check cross-file contracts registered in docs/CONTRACTS.md haven't drifted.

Usage:
    python scripts/check_contracts.py

Each check prints PASS/FAIL/WARN. Exits 0 iff every non-warn check passes.
Runs fully offline: it only imports app modules and reads source files as text.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.llm_router import _KNOWN_TOOLS, _ROUTER_SCHEMA  # noqa: E402
from app.core.response_formatter import _DATA_REPLY_PREFIX  # noqa: E402
from app.core.tools import (  # noqa: E402
    TOOL_DEFINITIONS,
    _VALID_NOTE_TYPES,
    _WRITE_TOOLS,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

_FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name}" + (f" ({detail})" if detail else ""))
        _FAILURES.append(name)


def warn(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS: {name}")
    else:
        print(f"WARN: {name}" + (f" ({detail})" if detail else ""))


def read(relpath: str) -> str:
    return (REPO_ROOT / relpath).read_text(encoding="utf-8")


def collect_note_type_enums(obj: object, found: set) -> None:
    """Recursively collect every enum list keyed under a "note_type" property."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "note_type" and isinstance(value, dict) and "enum" in value:
                found.update(value["enum"])
            collect_note_type_enums(value, found)
    elif isinstance(obj, list):
        for item in obj:
            collect_note_type_enums(item, found)


def main() -> int:
    # --- _DATA_REPLY_PREFIX byte-identical to the literal in llm.py ---
    literal = "Here are the details on file:"
    check(
        "_DATA_REPLY_PREFIX matches the literal used in app/core/llm.py",
        _DATA_REPLY_PREFIX == literal + "\n\n"
        and literal in read("app/core/llm.py")
        and literal in read("app/core/response_formatter.py"),
    )

    # --- magic strings occur in both producer and consumer files ---
    magic_strings = [
        ("No notes on file.", ["app/core/tools.py", "app/core/llm.py"]),
        (
            "Registered clients:",
            ["app/core/tools.py", "app/core/response_formatter.py"],
        ),
        (
            "pending confirmation",
            ["app/core/tools.py", "app/core/confirmations.py"],
        ),
    ]
    for literal_str, files in magic_strings:
        contents = {f: read(f) for f in files}
        check(
            f'"{literal_str}" occurs in {", ".join(files)}',
            all(literal_str in text for text in contents.values()),
        )

    # --- tool-name lists in sync with TOOL_DEFINITIONS ---
    definition_names = {d["function"]["name"] for d in TOOL_DEFINITIONS}

    check(
        "_KNOWN_TOOLS (llm_router.py) == TOOL_DEFINITIONS names",
        set(_KNOWN_TOOLS) == definition_names,
        f"_KNOWN_TOOLS={sorted(_KNOWN_TOOLS)} definitions={sorted(definition_names)}",
    )

    router_schema_enum = set(_ROUTER_SCHEMA["properties"]["tool"]["enum"]) - {"none"}
    check(
        "_ROUTER_SCHEMA tool enum (minus 'none') == TOOL_DEFINITIONS names",
        router_schema_enum == definition_names,
        f"schema={sorted(router_schema_enum)} definitions={sorted(definition_names)}",
    )

    allowed_write_tools = definition_names | {"update_client"}
    check(
        "_WRITE_TOOLS is a subset of TOOL_DEFINITIONS names (+ update_client alias)",
        set(_WRITE_TOOLS) <= allowed_write_tools,
        f"_WRITE_TOOLS={sorted(_WRITE_TOOLS)} allowed={sorted(allowed_write_tools)}",
    )

    # --- _VALID_NOTE_TYPES equals every inline note_type enum in TOOL_DEFINITIONS ---
    inline_note_types: set = set()
    collect_note_type_enums(TOOL_DEFINITIONS, inline_note_types)
    check(
        "_VALID_NOTE_TYPES == every inline note_type enum in TOOL_DEFINITIONS",
        set(_VALID_NOTE_TYPES) == inline_note_types,
        f"_VALID_NOTE_TYPES={sorted(_VALID_NOTE_TYPES)} inline={sorted(inline_note_types)}",
    )

    # --- every tool name has a card file (warn-only: naming may not be 1:1) ---
    card_dir = REPO_ROOT / "data" / "tool-knowledge"
    missing_cards = sorted(
        name for name in definition_names if not (card_dir / f"{name}.md").exists()
    )
    warn(
        "Every tool name has a data/tool-knowledge/<name>.md card",
        not missing_cards,
        f"missing={missing_cards}",
    )

    if _FAILURES:
        print(f"\n{len(_FAILURES)} contract check(s) FAILED: {', '.join(_FAILURES)}")
        return 1
    print("\nAll contract checks PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
