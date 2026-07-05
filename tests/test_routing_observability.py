"""Tests for tool routing deferral observability."""

import unittest
from unittest.mock import patch

from app.core.routing_observability import (
    get_stats,
    record_deferral,
    reset_stats,
)
from app.core.tool_router import ToolMatch


class RoutingObservabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_stats()

    def tearDown(self) -> None:
        reset_stats()

    def test_record_deferral_counts_near_miss(self) -> None:
        candidates = [
            ToolMatch(tool="list_clients", score=0.40, backend="token"),
            ToolMatch(tool="get_client", score=0.20, backend="token"),
        ]
        entry = record_deferral("dump the roster please", candidates, "token")

        self.assertTrue(entry.near_miss)
        stats = get_stats()
        self.assertEqual(stats["deferrals_total"], 1)
        self.assertEqual(stats["near_misses_total"], 1)
        self.assertEqual(len(stats["recent_near_misses"]), 1)
        self.assertEqual(stats["recent_near_misses"][0]["top_tools"][0]["tool"], "list_clients")

    def test_low_score_not_counted_as_near_miss(self) -> None:
        candidates = [ToolMatch(tool="get_client", score=0.10, backend="token")]
        entry = record_deferral("help me coach better", candidates, "token")

        self.assertFalse(entry.near_miss)
        stats = get_stats()
        self.assertEqual(stats["deferrals_total"], 1)
        self.assertEqual(stats["near_misses_total"], 0)
        self.assertEqual(stats["recent_near_misses"], [])

    def test_ring_buffer_caps_recent_entries(self) -> None:
        candidates = [ToolMatch(tool="list_clients", score=0.50, backend="token")]
        for index in range(60):
            record_deferral(f"message {index}", candidates, "token")

        stats = get_stats()
        self.assertEqual(stats["deferrals_total"], 60)
        self.assertLessEqual(len(stats["recent_near_misses"]), 5)


class ToolRouterDeferralHookTests(unittest.TestCase):
    def setUp(self) -> None:
        from app.core.tool_router import reset_index

        reset_stats()
        reset_index()

    def tearDown(self) -> None:
        from app.core.tool_router import reset_index

        reset_stats()
        reset_index()

    def test_classify_tool_records_deferral(self) -> None:

        from app.core.tool_router import build_index, classify_tool

        with (
            patch("app.core.config.settings.tool_router_enabled", True),
            patch("app.core.config.settings.tool_router_backend", "token"),
            patch("app.core.tool_router._embed_available", False),
            patch("app.core.tool_router._rerank_available", False),
        ):
            build_index(force=True)
            result = classify_tool("this message should defer xyz123")

        self.assertIsNone(result)
        stats = get_stats()
        self.assertEqual(stats["deferrals_total"], 1)


class HealthToolRouterStatsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_stats()

    def tearDown(self) -> None:
        reset_stats()

    async def test_health_includes_tool_router_block(self) -> None:
        from unittest.mock import AsyncMock

        record_deferral(
            "show all visitors",
            [ToolMatch(tool="list_clients", score=0.42, backend="token")],
            "token",
        )

        with (
            patch(
                "app.core.model_registry.probe_openrouter",
                new=AsyncMock(return_value=False),
            ),
            patch("app.core.embeddings.probe_embed_model", return_value=False),
            patch("app.core.rerank.rerank_probe_cached", return_value=False),
        ):
            from main import health_check

            payload = await health_check()

        self.assertIn("tool_router", payload)
        self.assertEqual(payload["tool_router"]["deferrals_total"], 1)
        self.assertEqual(payload["tool_router"]["near_misses_total"], 1)


if __name__ == "__main__":
    unittest.main()
