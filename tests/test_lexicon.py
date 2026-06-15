"""Tests for the domain synonym lexicon (app/core/lexicon.py)."""

from __future__ import annotations

import unittest


class LexiconNormalizationTests(unittest.TestCase):

    def _normalize(self, text: str) -> str:
        from app.core.lexicon import normalize_for_routing
        return normalize_for_routing(text)

    # -----------------------------------------------------------------------
    # Canonical input passes through unchanged
    # -----------------------------------------------------------------------

    def test_canonical_text_unchanged_no_extra_tokens(self) -> None:
        result = self._normalize("Who are my clients?")
        # Original text preserved at the start
        self.assertTrue(result.startswith("Who are my clients?"))

    def test_already_canonical_list_clients_no_redundant_expansion(self) -> None:
        result = self._normalize("List my clients")
        self.assertTrue(result.startswith("List my clients"))

    # -----------------------------------------------------------------------
    # Visitor / people synonyms → client / clients appended
    # -----------------------------------------------------------------------

    def test_visitor_triggers_client_expansion(self) -> None:
        result = self._normalize("Give me all visitors in table")
        self.assertIn("client", result.lower())

    def test_people_triggers_client_expansion(self) -> None:
        result = self._normalize("Show all people")
        self.assertIn("client", result.lower())

    def test_contact_triggers_client_expansion(self) -> None:
        result = self._normalize("Fetch all contacts")
        self.assertIn("client", result.lower())

    def test_attendee_triggers_client_expansion(self) -> None:
        result = self._normalize("Who are all my attendees?")
        self.assertIn("client", result.lower())

    def test_coachee_triggers_client_expansion(self) -> None:
        result = self._normalize("List my coachees")
        self.assertIn("client", result.lower())

    def test_participant_triggers_client_expansion(self) -> None:
        result = self._normalize("Show all participants")
        self.assertIn("client", result.lower())

    # -----------------------------------------------------------------------
    # Table / database synonyms → clients list appended
    # -----------------------------------------------------------------------

    def test_table_triggers_list_expansion(self) -> None:
        result = self._normalize("Show everyone in the table")
        self.assertIn("list", result.lower())

    def test_database_triggers_list_expansion(self) -> None:
        result = self._normalize("Who is in the database?")
        self.assertIn("clients", result.lower())

    def test_roster_triggers_list_expansion(self) -> None:
        result = self._normalize("Dump the roster")
        self.assertIn("list", result.lower())

    def test_records_triggers_list_expansion(self) -> None:
        result = self._normalize("Pull up the records")
        self.assertIn("clients", result.lower())

    # -----------------------------------------------------------------------
    # Retrieval verb synonyms
    # -----------------------------------------------------------------------

    def test_dump_triggers_show_expansion(self) -> None:
        result = self._normalize("Dump the database")
        self.assertIn("show", result.lower())

    def test_fetch_triggers_list_expansion(self) -> None:
        result = self._normalize("Fetch all contacts")
        self.assertIn("list", result.lower())

    def test_retrieve_triggers_get_expansion(self) -> None:
        result = self._normalize("Retrieve Sara's data")
        self.assertIn("get", result.lower())

    # -----------------------------------------------------------------------
    # Note / memo synonyms
    # -----------------------------------------------------------------------

    def test_memo_triggers_note_expansion(self) -> None:
        result = self._normalize("Pull up all memos for Ali")
        self.assertIn("note", result.lower())

    def test_entry_triggers_note_expansion(self) -> None:
        result = self._normalize("Show all entries for Mohammad")
        self.assertIn("note", result.lower())

    # -----------------------------------------------------------------------
    # Goal / objective synonyms
    # -----------------------------------------------------------------------

    def test_objective_triggers_goal_expansion(self) -> None:
        result = self._normalize("What are Ali's objectives?")
        self.assertIn("goal", result.lower())

    def test_aim_triggers_goal_expansion(self) -> None:
        result = self._normalize("What are Ali's aims?")
        self.assertIn("goal", result.lower())

    def test_milestone_triggers_goal_expansion(self) -> None:
        result = self._normalize("What milestones has Sara reached?")
        self.assertIn("goal", result.lower())

    # -----------------------------------------------------------------------
    # Token backend: out-of-vocab message matches list_clients with lexicon
    # -----------------------------------------------------------------------

    def test_visitors_in_table_matches_list_clients_token_backend(self) -> None:
        """Core regression: the motivating failure case must now route correctly."""
        import os
        os.environ["TOOL_ROUTER_BACKEND"] = "token"
        os.environ["TOOL_ROUTER_ENABLED"] = "true"

        from app.core.tool_router import build_index, classify_tool, reset_index
        reset_index()
        build_index()

        match = classify_tool("Give me all visitors in table", threshold=0.15, margin=0.05)
        self.assertIsNotNone(match, "Expected list_clients match via lexicon expansion")
        assert match is not None
        self.assertEqual(match.tool, "list_clients")

    def test_roster_matches_list_clients_token_backend(self) -> None:
        import os
        os.environ["TOOL_ROUTER_BACKEND"] = "token"
        from app.core.tool_router import build_index, classify_tool, reset_index
        reset_index()
        build_index()
        match = classify_tool("Dump the roster", threshold=0.15, margin=0.05)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.tool, "list_clients")

    def test_database_matches_list_clients_token_backend(self) -> None:
        import os
        os.environ["TOOL_ROUTER_BACKEND"] = "token"
        from app.core.tool_router import build_index, classify_tool, reset_index
        reset_index()
        build_index()
        match = classify_tool("Who is in the database?", threshold=0.15, margin=0.05)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.tool, "list_clients")

    def test_objectives_matches_list_client_notes_token_backend(self) -> None:
        import os
        os.environ["TOOL_ROUTER_BACKEND"] = "token"
        from app.core.tool_router import build_index, classify_tool, reset_index
        reset_index()
        build_index()
        match = classify_tool("What are Ali's objectives?", threshold=0.15, margin=0.05)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.tool, "list_client_notes")
