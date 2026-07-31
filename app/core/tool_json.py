"""Defensive JSON parsing for tool calls small local models emit as text.

Centralizes the tolerant-JSON helpers that used to be duplicated across
``client_intents.py`` and ``llm.py`` (CQ-02 consolidation): finding a
tool-call-shaped JSON object embedded in free-form model output, parsing it
even when the model used Python literals instead of JSON ones, and telling
apart a valid tool call from a malformed one.

The same tolerance is reused wherever a small model's JSON reaches us: provider
tool-call ``arguments`` (:func:`parse_tool_arguments`), assistant replies
wrapped in a JSON envelope, and the Open WebUI task replies the UI parses as
strict JSON (:func:`normalize_json_output`).  Every helper degrades to ``None``
or to the original text — none of them raise.
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

# Small models routinely wrap JSON in a Markdown code fence even when the prompt
# asks for bare JSON, so the fence is stripped before any parse attempt.
_CODE_FENCE_RE = re.compile(r"```[ \t]*[A-Za-z0-9_+-]*[ \t]*\r?\n?(.*?)```", re.DOTALL)


def strip_code_fences(content: str) -> str:
    """Return the body of the first Markdown code fence in *content*.

    Falls back to *content* with surrounding whitespace removed when there is
    no fenced block.
    """
    match = _CODE_FENCE_RE.search(content)
    if match:
        return match.group(1).strip()
    return content.strip()


def _object_spans(text: str, *, start: int = 0) -> list[tuple[int, int]]:
    """Return ``(start, end)`` indices of balanced top-level ``{...}`` spans.

    String literals are tracked, so a brace inside a value — a client note that
    contains ``}``, for instance — does not close the object early.
    """
    spans: list[tuple[int, int]] = []
    depth = 0
    opened = -1
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                opened = index
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
            if depth == 0:
                spans.append((opened, index + 1))
    return spans


def _extract_tool_payload(data: dict[str, Any]) -> Optional[tuple[str, dict[str, Any]]]:
    # OpenAI's nested shape, emitted as text by models that were trained on it:
    # ``{"type": "function", "function": {"name": ..., "arguments": {...}}}``.
    nested = data.get("function")
    if isinstance(nested, dict):
        payload = _extract_tool_payload(nested)
        if payload:
            return payload

    tool_name = data.get("tool") or data.get("name") or data.get("function")
    params: Any = None
    for key in ("parameters", "arguments", "params"):
        if key in data:
            params = data[key]
            break
    # Double-encoded arguments: ``{"name": "get_client", "arguments": "{\"id\": 1}"}``.
    if isinstance(params, str):
        decoded = loads_json_tolerant(params)
        if decoded is None:
            decoded = extract_json_object(params)
        params = decoded
    if isinstance(tool_name, str) and isinstance(params, dict):
        return tool_name, params
    return None


def _is_tool_shaped_dict(data: dict[str, Any]) -> bool:
    tool_keys = {"name", "tool", "function"}
    param_keys = {"parameters", "arguments", "params"}
    return bool(set(data.keys()) & tool_keys) and bool(set(data.keys()) & param_keys)


def loads_json_tolerant(s: str) -> Optional[dict[str, Any]]:
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


def extract_json_object(content: str) -> Optional[dict[str, Any]]:
    """Parse the JSON object a model wrapped in a code fence or in prose.

    An object is accepted only when it is the whole (fence-stripped) content,
    starts it, or ends it — the three shapes small models actually produce
    ("```json {...}```", "Here is the JSON:\\n{...}", "{...}\\nLet me know").
    A reply that merely mentions an object mid-sentence is left alone.
    Returns ``None`` when no such object parses.
    """
    for text in (strip_code_fences(content), content.strip()):
        if not text:
            continue
        data = loads_json_tolerant(text)
        if data is not None:
            return data
        for start, end in _object_spans(text):
            if start != 0 and end != len(text):
                continue
            data = loads_json_tolerant(text[start:end])
            if data is not None:
                return data
    return None


def normalize_json_output(content: str) -> str:
    """Return *content* as a bare, valid JSON object when one can be recovered.

    Open WebUI parses task replies (title, tags, follow-ups) as strict JSON, so
    a code fence, a prose preamble, or Python literals turn an otherwise correct
    small-model answer into a parse error on the UI side.  Returned unchanged
    when no object is recoverable — there is nothing better to send.
    """
    data = extract_json_object(content)
    if data is None:
        return content
    return json.dumps(data, ensure_ascii=False)


def parse_tool_arguments(raw: Any) -> Optional[dict[str, Any]]:
    """Best-effort parse of a tool call's ``arguments`` field.

    Providers receive ``arguments`` as a dict or as a JSON string.  Small models
    frequently emit a *malformed* string: Python literals, a code fence, prose,
    or output truncated at ``num_predict``.  Returns the parsed arguments, or
    ``None`` when nothing usable can be recovered — callers log and fall back to
    empty arguments rather than letting ``JSONDecodeError`` abort the turn.
    """
    if isinstance(raw, dict):
        return raw
    if raw is None:
        return {}
    if not isinstance(raw, str):
        return None
    if not raw.strip():
        return {}
    data = loads_json_tolerant(raw)
    if data is not None:
        return data
    return extract_json_object(raw)


def _embedded_tool_json_candidates(content: str) -> list[str]:
    """Collect JSON substrings that may contain a text-based tool call."""
    candidates: list[str] = []
    bases: list[str] = []
    for text in (content.strip(), strip_code_fences(content)):
        if text and text not in bases:
            bases.append(text)
    candidates.extend(bases)
    for base in bases:
        for pattern in _TOOL_JSON_KEY_PATTERNS:
            for match in re.finditer(pattern, base):
                spans = _object_spans(base, start=match.start())
                if not spans:
                    continue
                start, end = spans[0]
                candidate = base[start:end]
                if candidate not in candidates:
                    candidates.append(candidate)
    return candidates


def looks_like_malformed_tool_call(content: str) -> bool:
    """True when the model emitted tool-call-shaped JSON without a valid call."""
    if parse_text_tool_call(content):
        return False

    stripped = content.strip()
    if not stripped:
        return False

    for candidate in _embedded_tool_json_candidates(stripped):
        data = loads_json_tolerant(candidate)
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
        data = loads_json_tolerant(candidate)
        if data is None:
            continue

        payload = _extract_tool_payload(data)
        if payload:
            return payload

        error_text = data.get("error")
        if isinstance(error_text, str):
            for nested in _embedded_tool_json_candidates(error_text):
                nested_data = loads_json_tolerant(nested)
                if nested_data is not None:
                    payload = _extract_tool_payload(nested_data)
                    if payload:
                        return payload
    return None
