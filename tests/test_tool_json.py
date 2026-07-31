"""Tolerant JSON handling for small-model output.

Regression cover for the malformed-JSON paths an 8B model actually produces:
code fences, prose preambles, Python literals, double-encoded arguments, the
nested OpenAI tool-call shape, and braces inside string values. Each of these
used to end a turn with a parse error (or a misleading "model unavailable"
reply) instead of the answer the model was trying to give.
"""

from __future__ import annotations

import unittest

from app.core.tool_json import (
    extract_json_object,
    looks_like_malformed_tool_call,
    normalize_json_output,
    parse_text_tool_call,
    parse_tool_arguments,
    strip_code_fences,
)


class StripCodeFencesTests(unittest.TestCase):
    def test_strips_json_fence(self) -> None:
        self.assertEqual(
            strip_code_fences('```json\n{"title": "Weekly check-in"}\n```'),
            '{"title": "Weekly check-in"}',
        )

    def test_strips_bare_fence(self) -> None:
        self.assertEqual(strip_code_fences('```\n{"a": 1}\n```'), '{"a": 1}')

    def test_unfenced_content_only_stripped(self) -> None:
        self.assertEqual(strip_code_fences('  {"a": 1}  '), '{"a": 1}')


class ExtractJsonObjectTests(unittest.TestCase):
    def test_fenced_object(self) -> None:
        self.assertEqual(
            extract_json_object('```json\n{"tags": ["goals"]}\n```'),
            {"tags": ["goals"]},
        )

    def test_prose_preamble(self) -> None:
        self.assertEqual(
            extract_json_object('Here is the JSON:\n{"title": "Ali\'s progress"}'),
            {"title": "Ali's progress"},
        )

    def test_trailing_commentary(self) -> None:
        self.assertEqual(
            extract_json_object('{"title": "Goal setting"}\n\nLet me know if that works!'),
            {"title": "Goal setting"},
        )

    def test_python_literals(self) -> None:
        self.assertEqual(
            extract_json_object('{"done": True, "note": None}'),
            {"done": True, "note": None},
        )

    def test_brace_inside_string_value(self) -> None:
        # The old brace counter closed the object at the first "}" it saw, even
        # inside a quoted value.
        self.assertEqual(
            extract_json_object('{"note": "he said }: done", "id": 3}'),
            {"note": "he said }: done", "id": 3},
        )

    def test_object_mid_sentence_is_left_alone(self) -> None:
        # Not the whole reply, nor its start or end → not an envelope.
        self.assertIsNone(
            extract_json_object('You could log it as {"mood": 5} each evening, then review.')
        )

    def test_no_object(self) -> None:
        self.assertIsNone(extract_json_object("Just a plain coaching answer."))

    def test_truncated_object(self) -> None:
        self.assertIsNone(extract_json_object('{"title": "cut off mid'))


class NormalizeJsonOutputTests(unittest.TestCase):
    def test_fenced_task_reply_becomes_bare_json(self) -> None:
        self.assertEqual(
            normalize_json_output('```json\n{"follow_ups": ["What is next?"]}\n```'),
            '{"follow_ups": ["What is next?"]}',
        )

    def test_python_literals_repaired(self) -> None:
        self.assertEqual(normalize_json_output('{"ok": True}'), '{"ok": true}')

    def test_non_ascii_preserved(self) -> None:
        self.assertEqual(normalize_json_output('{"title": "پیشرفت"}'), '{"title": "پیشرفت"}')

    def test_unrecoverable_returned_unchanged(self) -> None:
        self.assertEqual(normalize_json_output("no json here"), "no json here")


class ParseToolArgumentsTests(unittest.TestCase):
    def test_dict_passthrough(self) -> None:
        self.assertEqual(parse_tool_arguments({"client_id": 3}), {"client_id": 3})

    def test_json_string(self) -> None:
        self.assertEqual(parse_tool_arguments('{"client_id": 3}'), {"client_id": 3})

    def test_python_literal_string(self) -> None:
        self.assertEqual(parse_tool_arguments('{"active": True}'), {"active": True})

    def test_fenced_string(self) -> None:
        self.assertEqual(parse_tool_arguments('```json\n{"name": "Ali"}\n```'), {"name": "Ali"})

    def test_empty_forms_mean_no_arguments(self) -> None:
        for raw in (None, "", "   ", "{}", {}):
            with self.subTest(raw=raw):
                self.assertEqual(parse_tool_arguments(raw), {})

    def test_unrecoverable_returns_none(self) -> None:
        # None signals the provider to log and fall back to {} — never raise.
        self.assertIsNone(parse_tool_arguments('{"name": "Ali", "notes": [tru'))
        self.assertIsNone(parse_tool_arguments("not json at all"))
        self.assertIsNone(parse_tool_arguments(42))


class TextToolCallTests(unittest.TestCase):
    def test_double_encoded_arguments(self) -> None:
        # {"name": ..., "arguments": "<json string>"} — used to be reported as a
        # malformed call, costing a second full completion.
        self.assertEqual(
            parse_text_tool_call('{"name": "get_client", "arguments": "{\\"client_id\\": 2}"}'),
            ("get_client", {"client_id": 2}),
        )

    def test_nested_openai_shape(self) -> None:
        self.assertEqual(
            parse_text_tool_call(
                '{"type": "function", "function": '
                '{"name": "list_clients", "arguments": {}}}'
            ),
            ("list_clients", {}),
        )

    def test_fenced_tool_call(self) -> None:
        self.assertEqual(
            parse_text_tool_call('```json\n{"tool": "list_clients", "parameters": {}}\n```'),
            ("list_clients", {}),
        )

    def test_empty_arguments_still_a_valid_call(self) -> None:
        self.assertEqual(
            parse_text_tool_call('{"name": "list_clients", "arguments": "{}"}'),
            ("list_clients", {}),
        )

    def test_plain_text_is_not_a_tool_call(self) -> None:
        self.assertIsNone(parse_text_tool_call("Let's talk about Ali's goals."))

    def test_truncated_call_reported_malformed(self) -> None:
        self.assertTrue(
            looks_like_malformed_tool_call('{"tool": "get_client", "parameters": 7}')
        )


if __name__ == "__main__":
    unittest.main()
