"""Defensive JSON parsing for tool calls small local models emit as text.

Centralizes the tolerant-JSON helpers that used to be duplicated across
``client_intents.py`` and ``llm.py`` (CQ-02 consolidation): finding a
tool-call-shaped JSON object embedded in free-form model output, parsing it
even when the model used Python literals instead of JSON ones, and telling
apart a valid tool call from a malformed one.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

_TOOL_JSON_KEY_PATTERNS = (
    r"\{[^{}]*\"tool\"\s*:",
    r"\{[^{}]*\"name\"\s*:",
    r"\{[^{}]*\"function\"\s*:",
)

# Some models (e.g. llama3.1) emit Python-style literals instead of JSON-standard
# ones: ``True``/``False``/``None`` instead of ``true``/``false``/``null``.
# These patterns normalise them so ``json.loads`` can parse the output.
_PY_TRUE = re.compile(r"\bTrue\b")
_PY_FALSE = re.compile(r"\bFalse\b")
_PY_NONE = re.compile(r"\bNone\b")


def _extract_tool_payload(data: dict[str, Any]) -> Optional[tuple[str, dict[str, Any]]]:
    tool_name = data.get("tool") or data.get("name") or data.get("function")
    params: Any = None
    for key in ("parameters", "arguments", "params"):
        if key in data:
            params = data[key]
            break
    if isinstance(tool_name, str) and isinstance(params, dict):
        return tool_name, params
    return None


def _is_tool_shaped_dict(data: dict[str, Any]) -> bool:
    tool_keys = {"name", "tool", "function"}
    param_keys = {"parameters", "arguments", "params"}
    return bool(set(data.keys()) & tool_keys) and bool(set(data.keys()) & param_keys)


def _loads_json_tolerant(s: str) -> Optional[dict[str, Any]]:
    """Parse *s* as a JSON object, falling back to Python-literal normalisation.

    ``json.loads`` is tried first.  If it fails, Python-style literals
    (``True`` / ``False`` / ``None``) are replaced with their JSON equivalents
    (``true`` / ``false`` / ``null``) and parsing is retried.  Returns the
    parsed ``dict`` on success, or ``None`` on failure.

    The normalisation is applied only as a fallback to avoid altering string
    values in well-formed JSON.
    """
    try:
        data = json.loads(s)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass

    normalized = _PY_FALSE.sub("false", _PY_TRUE.sub("true", _PY_NONE.sub("null", s)))
    try:
        data = json.loads(normalized)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _embedded_tool_json_candidates(content: str) -> list[str]:
    """Collect JSON substrings that may contain a text-based tool call."""
    candidates = [content.strip()]
    for pattern in _TOOL_JSON_KEY_PATTERNS:
        for match in re.finditer(pattern, content):
            start = match.start()
            depth = 0
            for index in range(start, len(content)):
                char = content[index]
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        candidates.append(content[start : index + 1])
                        break
    return candidates


def looks_like_malformed_tool_call(content: str) -> bool:
    """True when the model emitted tool-call-shaped JSON without a valid call."""
    if parse_text_tool_call(content):
        return False

    stripped = content.strip()
    if not stripped:
        return False

    for candidate in _embedded_tool_json_candidates(stripped):
        data = _loads_json_tolerant(candidate)
        if data is not None and _is_tool_shaped_dict(data):
            if _extract_tool_payload(data) is None:
                return True
    return False


def parse_text_tool_call(content: str) -> Optional[tuple[str, dict[str, Any]]]:
    """Parse tool calls some models emit as JSON text instead of native tool_calls.

    Handles both well-formed JSON and the Python-style literals (``True`` /
    ``False`` / ``None``) that some local models (e.g. llama3.1) emit instead
    of the JSON-standard ``true`` / ``false`` / ``null``.
    """
    stripped = content.strip()
    if not stripped:
        return None

    for candidate in _embedded_tool_json_candidates(stripped):
        data = _loads_json_tolerant(candidate)
        if data is None:
            continue

        payload = _extract_tool_payload(data)
        if payload:
            return payload

        error_text = data.get("error")
        if isinstance(error_text, str):
            for nested in _embedded_tool_json_candidates(error_text):
                nested_data = _loads_json_tolerant(nested)
                if nested_data is not None:
                    payload = _extract_tool_payload(nested_data)
                    if payload:
                        return payload
    return None
