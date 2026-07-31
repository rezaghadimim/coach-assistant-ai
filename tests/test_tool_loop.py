"""AI-02 — agentic tool-loop iteration-exhaustion and multi-call paths.

Exercises two previously-untested branches of ``_generate_with_tools``:
  1. iteration exhaustion → the "unable to complete" fallback.
  2. two sequential tool calls followed by a final text answer → both tools
     execute and the text is returned.

Uses a scripted fake provider passed directly to the loop, so no HTTP mocking
is needed and the tool loop is exercised in isolation.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.core.llm import _MAX_TOOL_ITERATIONS, _generate_with_tools
from app.core.llm_providers.types import CompletionResult, ToolCall
from app.core.tools import TOOL_DEFINITIONS, execute_tool
from app.memory.store import MemoryStore


def _tool_call_result(name: str, arguments: dict) -> CompletionResult:
    tc = ToolCall(id=f"call_{name}", name=name, arguments=arguments)
    return CompletionResult(
        content="",
        tool_calls=[tc],
        assistant_message={"role": "assistant", "content": "", "tool_calls": [name]},
    )


def _text_result(content: str) -> CompletionResult:
    return CompletionResult(
        content=content,
        tool_calls=[],
        assistant_message={"role": "assistant", "content": content},
    )


class _ScriptedProvider:
    """Provider stub returning a pre-scripted sequence of completions.

    If the script is exhausted it keeps returning the last item, so an
    "always tool-calls" script naturally drives the loop to exhaustion.
    """

    def __init__(self, script: list[CompletionResult]) -> None:
        self._script = script
        self.calls = 0
        self.executed_tools: list[str] = []
        self.tools_seen: list[object] = []
        self.formats_seen: list[object] = []

    async def complete(self, messages, *, tools=None, temperature=None, **kwargs):
        self.calls += 1
        self.tools_seen.append(tools)
        self.formats_seen.append(kwargs.get("format"))
        idx = min(self.calls - 1, len(self._script) - 1)
        return self._script[idx]

    def tool_result_message(self, tool_call: ToolCall, result: str) -> dict:
        self.executed_tools.append(tool_call.name)
        return {"role": "tool", "tool_name": tool_call.name, "content": result}


class ToolLoopTests(unittest.IsolatedAsyncioTestCase):
    def _store(self, tmp: str) -> MemoryStore:
        store = MemoryStore(str(Path(tmp) / "loop.db"))
        # A client so read tools return non-terminal "info" outcomes that keep
        # the loop going rather than erroring out.
        execute_tool(
            "create_client",
            {"client_id": "ali", "name": "Ali", "confirmed": True},
            store,
        )
        return store

    async def test_iteration_exhaustion_returns_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            # Every iteration asks for the same non-terminal read → never final.
            provider = _ScriptedProvider(
                [_tool_call_result("list_clients", {})]
            )
            reply = await _generate_with_tools(
                [{"role": "user", "content": "keep working on the plan"}],
                "system",
                TOOL_DEFINITIONS,
                store,
                provider=provider,
                skip_direct_reply=True,
            )

        self.assertIn("unable to complete", reply.lower())
        self.assertEqual(provider.calls, _MAX_TOOL_ITERATIONS)

    async def test_two_sequential_tool_calls_then_final_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            provider = _ScriptedProvider(
                [
                    _tool_call_result("list_clients", {}),
                    _tool_call_result("get_client", {"client_id": "ali"}),
                    _text_result("Here is a short coaching plan for you."),
                ]
            )
            reply = await _generate_with_tools(
                [{"role": "user", "content": "review then advise on the plan"}],
                "system",
                TOOL_DEFINITIONS,
                store,
                provider=provider,
                skip_direct_reply=True,
            )

        self.assertIn("list_clients", provider.executed_tools)
        self.assertIn("get_client", provider.executed_tools)
        self.assertIn("coaching plan", reply)
        self.assertEqual(provider.calls, 3)

    async def test_openwebui_task_skips_tool_loop(self) -> None:
        # Bug 3 regression: Open WebUI meta-tasks (follow-ups, title, tags) must
        # run as a single plain completion with NO tools, even when the chat
        # history mentions a client. Otherwise the model calls DB tools from
        # stale context (spurious reads + stale create_client previews).
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            provider = _ScriptedProvider(
                [_text_result('{"follow_ups": ["What is next for Ali?"]}')]
            )
            messages = [
                {"role": "user", "content": "Tell me about Ali"},
                {"role": "assistant", "content": "Ali is making progress."},
                {
                    "role": "user",
                    "content": (
                        "### Task:\nSuggest 3-5 relevant follow-up questions "
                        "based on the chat history."
                    ),
                },
            ]
            reply = await _generate_with_tools(
                messages,
                "system",
                TOOL_DEFINITIONS,
                store,
                provider=provider,
            )

        # Raw JSON returned unsanitized for the UI to parse.
        self.assertIn("follow_ups", reply)
        # Single completion, no tool execution, tools withheld from the provider.
        self.assertEqual(provider.calls, 1)
        self.assertEqual(provider.executed_tools, [])
        self.assertEqual(provider.tools_seen, [None])

    async def test_json_task_is_constrained_and_normalized(self) -> None:
        # Open WebUI parses this reply as strict JSON. Unconstrained, a small
        # model fences it and adds a preamble, and the UI reports a JSON error.
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            provider = _ScriptedProvider(
                [_text_result(
                    'Sure! Here is the JSON:\n```json\n{"title": "Ali\'s progress"}\n```'
                )]
            )
            messages = [{
                "role": "user",
                "content": (
                    "### Task:\nGenerate a concise, 3-5 word title.\n"
                    '### Output:\nJSON format: { "title": "your concise title here" }'
                ),
            }]
            reply = await _generate_with_tools(
                messages, "system", TOOL_DEFINITIONS, store, provider=provider
            )

        # JSON mode requested from Ollama, and the reply is bare parseable JSON.
        self.assertEqual(provider.formats_seen, ["json"])
        self.assertEqual(json.loads(reply), {"title": "Ali's progress"})

    async def test_non_json_task_is_left_unconstrained(self) -> None:
        # Not every Open WebUI task wants JSON; forcing JSON mode would corrupt
        # a plain-text task reply.
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            provider = _ScriptedProvider([_text_result("Weekly check-in")])
            messages = [{
                "role": "user",
                "content": "### Task:\nGenerate a concise, 3-5 word title.\n### Output:\nTitle only.",
            }]
            reply = await _generate_with_tools(
                messages, "system", TOOL_DEFINITIONS, store, provider=provider
            )

        self.assertEqual(provider.formats_seen, [None])
        self.assertEqual(reply, "Weekly check-in")


if __name__ == "__main__":
    unittest.main()
