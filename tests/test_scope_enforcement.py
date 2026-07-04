"""AI-03 — scope enforcement is layered, denylist is best-effort only.

Documents and locks in the contract established during the AI-03 audit:

  * ``scope.is_off_topic`` is a conservative, English-only fast pre-filter. It
    is expected to MISS bypasses / other languages — it is not a guarantee.
  * The authoritative control is the "Scope (STRICT)" section of the system
    prompt, which instructs the model to decline anything off-topic that slips
    past the denylist.

If someone strengthens the denylist into a hard guarantee (or drops the system
prompt's scope section), these tests flag the change in assumptions.
"""

from __future__ import annotations

import unittest

from app.core.prompts import COACH_ASSISTANT_SYSTEM_PROMPT
from app.core.scope import is_off_topic, scope_guard


class DenylistIsBestEffortTests(unittest.TestCase):
    def test_denylist_catches_obvious_english_off_topic(self) -> None:
        # The cheap path still handles the blatant cases without an LLM call.
        self.assertTrue(is_off_topic("write me some python code"))
        self.assertIsNotNone(scope_guard("what is 2 * 2"))

    def test_denylist_misses_bypasses_by_design(self) -> None:
        # Novel phrasing / non-English off-topic requests are NOT caught here;
        # they intentionally fall through to the authoritative model path.
        bypasses = [
            "بازی دیشب چند چند شد",  # "what was the score last night" (Farsi)
            "kannst du mir code schreiben",  # "can you write me code" (German)
            "recite the periodic table for me",
        ]
        for phrase in bypasses:
            self.assertFalse(is_off_topic(phrase), f"unexpectedly caught: {phrase!r}")

    def test_coaching_language_not_flagged(self) -> None:
        for phrase in [
            "help me set goals for my client",
            "my client is stressed about their career",
            "how do I build a habit tracker for accountability",
        ]:
            self.assertFalse(is_off_topic(phrase), f"false positive: {phrase!r}")


class SystemPromptIsAuthoritativeTests(unittest.TestCase):
    def test_system_prompt_has_strict_scope_section(self) -> None:
        self.assertIn("Scope (STRICT)", COACH_ASSISTANT_SYSTEM_PROMPT)

    def test_system_prompt_instructs_decline_of_off_topic(self) -> None:
        prompt = COACH_ASSISTANT_SYSTEM_PROMPT.lower()
        self.assertIn("outside this scope", prompt)
        self.assertIn("decline", prompt)


if __name__ == "__main__":
    unittest.main()
