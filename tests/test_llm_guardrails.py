"""Tests for deterministic anti-hallucination guardrails in app.core.llm.

These cover the non-LLM guards that keep the small local model from inventing
client data:

- ``_is_data_request``  — broadened recall (guardrail D)
- ``_references_unknown_client`` — entity grounding short-circuit (guardrail C)
- ``_ground_data_reply`` — fabricated-PII guard on free-form replies (guardrail A/B)
- ``_notes_grounded`` — fabricated note/goal/decision content guard (guardrail E)
"""

import unittest

from app.api.chat import reset_runtime_state, store
from app.core.llm import (
    _ground_data_reply,
    _is_data_request,
    _notes_grounded,
    _references_unknown_client,
)
from app.core.tools import execute_tool


def _create_client(client_id: str, name: str, *, email: str = "", phone: str = "") -> None:
    args = {"client_id": client_id, "name": name, "confirmed": True}
    if email:
        args["email"] = email
    if phone:
        args["phone"] = phone
    execute_tool("create_client", args, store)


class IsDataRequestTests(unittest.TestCase):
    """Guardrail D: broadened recall without losing the object-noun gate."""

    def test_existing_patterns_still_match(self) -> None:
        self.assertTrue(_is_data_request("list all clients"))
        self.assertTrue(_is_data_request("show me Ali's notes"))
        self.assertTrue(_is_data_request("what is Ali's email"))

    def test_contractions_now_match(self) -> None:
        self.assertTrue(_is_data_request("what's Sara's email"))
        self.assertTrue(_is_data_request("who's on my roster"))
        self.assertTrue(_is_data_request("where's the phone number for Ali"))

    def test_new_lookup_phrases_match(self) -> None:
        self.assertTrue(_is_data_request("do we have any notes on Sara"))
        self.assertTrue(_is_data_request("do I have an email for Ali"))
        self.assertTrue(_is_data_request("look up the phone for Reza"))

    def test_coaching_questions_without_object_noun_excluded(self) -> None:
        # No trigger-verb + data-object-noun pair → not a data request.
        self.assertFalse(_is_data_request("how can I help a client feel less stuck"))
        self.assertFalse(_is_data_request("share an analogy about fear of failure"))
        self.assertFalse(_is_data_request("how do I run a GROW session"))

    def test_short_possessive_forms_match(self) -> None:
        # Terse queries with no leading verb previously slipped past the gate and
        # reached the free-form loop ungrounded (guardrail broadening for shorts).
        self.assertTrue(_is_data_request("Sara's goals?"))
        self.assertTrue(_is_data_request("Ali's notes"))
        self.assertTrue(_is_data_request("Sara's email"))
        self.assertTrue(_is_data_request("Nima's occupation"))

    def test_short_pronoun_forms_match(self) -> None:
        self.assertTrue(_is_data_request("her goals"))
        self.assertTrue(_is_data_request("his decisions"))
        self.assertTrue(_is_data_request("her age"))
        self.assertTrue(_is_data_request("their progress"))

    def test_pronoun_followed_by_non_data_word_excluded(self) -> None:
        # The word after the pronoun must be a data noun; "her set goals" is advice.
        self.assertFalse(_is_data_request("help her set goals this week"))
        self.assertFalse(_is_data_request("my plan for the session"))

    def test_advice_phrasing_with_object_noun_overtriggers_by_design(self) -> None:
        # "...good first goal..." contains the object noun "goal", so the broad
        # _is_data_request fires — exactly as the original "what is" form did.
        # This is harmless: the hardened LLM router classifies it "none" and the
        # entity/PII guards never engage without a real client on file.
        self.assertTrue(_is_data_request("what's a good first goal to set"))


class ReferencesUnknownClientTests(unittest.TestCase):
    """Guardrail C: abstain when a named client is not on file."""

    def setUp(self) -> None:
        reset_runtime_state()

    def test_unknown_client_lookup_is_flagged(self) -> None:
        ref = _references_unknown_client("what is Sara's email", store)
        self.assertIsNotNone(ref)
        self.assertIn("sara", ref.lower())

    def test_known_client_lookup_passes_through(self) -> None:
        _create_client("sara", "Sara", email="sara@example.com")
        self.assertIsNone(_references_unknown_client("what is Sara's email", store))

    def test_non_lookup_message_returns_none(self) -> None:
        # No possessive/about/field lookup reference at all.
        self.assertIsNone(_references_unknown_client("how do I run a GROW session", store))


class GroundDataReplyTests(unittest.TestCase):
    """Guardrail A/B: replace replies that invent PII absent from the record."""

    def setUp(self) -> None:
        reset_runtime_state()

    def test_fabricated_email_is_replaced_with_real_record(self) -> None:
        _create_client("ali", "Ali", email="ali@example.com")
        fabricated = "Ali's email is fake@hacker.com."
        out = _ground_data_reply(fabricated, "what is Ali's email", store)
        self.assertNotIn("fake@hacker.com", out)
        self.assertIn("ali@example.com", out)

    def test_correct_email_is_preserved(self) -> None:
        _create_client("ali", "Ali", email="ali@example.com")
        good = "Ali's email is ali@example.com."
        out = _ground_data_reply(good, "what is Ali's email", store)
        self.assertEqual(out, good)

    def test_non_data_request_is_untouched(self) -> None:
        _create_client("ali", "Ali", email="ali@example.com")
        advice = "You might try asking Ali an open question like fake@x.com."
        # Not a data request → guard does not engage even with a stray token.
        out = _ground_data_reply(advice, "how can I support Ali emotionally", store)
        self.assertEqual(out, advice)

    def test_unresolvable_client_is_untouched(self) -> None:
        # No client on file resolves from the message → nothing to ground against.
        reply = "Their email is something@example.com."
        out = _ground_data_reply(reply, "what is their email", store)
        self.assertEqual(out, reply)

    def test_fabricated_goal_is_replaced_when_no_notes_on_file(self) -> None:
        _create_client("ali", "Ali")
        fabricated = "Ali's goal is to become a team lead by next quarter."
        out = _ground_data_reply(fabricated, "what are Ali's goals", store)
        self.assertNotIn("team lead", out)
        self.assertIn("No notes on file.", out)

    def test_honest_no_notes_reply_is_preserved(self) -> None:
        _create_client("ali", "Ali")
        honest = "There's nothing on file yet for Ali."
        out = _ground_data_reply(honest, "what are Ali's goals", store)
        self.assertEqual(out, honest)


class NotesGroundedTests(unittest.TestCase):
    """Guardrail E: block invented note/goal/decision content."""

    def test_content_claim_without_notes_fails(self) -> None:
        record = "## Profile\nClient ID: ali\n\n## Notes\nNo notes on file."
        reply = "Ali decided to start a new fitness routine."
        self.assertFalse(_notes_grounded(record, reply))

    def test_plain_reply_without_notes_passes(self) -> None:
        record = "## Profile\nClient ID: ali\n\n## Notes\nNo notes on file."
        reply = "There's nothing on file yet for Ali."
        self.assertTrue(_notes_grounded(record, reply))

    def test_content_claim_with_real_notes_passes(self) -> None:
        record = (
            "## Profile\nClient ID: ali\n\n## Notes\n"
            "- [GOAL] (2026-05-01)\n  Become a team lead by next quarter."
        )
        reply = "Ali's goal is to become a team lead by next quarter."
        self.assertTrue(_notes_grounded(record, reply))


if __name__ == "__main__":
    unittest.main()
