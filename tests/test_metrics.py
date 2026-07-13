"""Prometheus /metrics endpoint tests (IMP-03).

The endpoint is unauthenticated (like /health) and its request-duration
counters increment on every request via the ASGI middleware in main.py.
"""

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.api import metrics
from app.core.config import settings
from main import app

_AVAILABILITY = {
    "ollama": True,
    "openrouter": False,
    "embeddings": True,
    "tool_router": True,
    "rerank": False,
}


class MetricsEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        # Reset the process-wide request counters so assertions are deterministic
        # regardless of test ordering.
        with metrics._lock:
            metrics._request_count = 0
            metrics._request_duration_seconds_sum = 0.0
        self._old_key = settings.api_key
        self._old_debug = settings.debug
        settings.api_key = ""
        settings.debug = True

    def tearDown(self) -> None:
        settings.api_key = self._old_key
        settings.debug = self._old_debug

    def _get_metrics(self):
        # Avoid real network probes in _layer_availability.
        with patch(
            "app.core.health.layer_availability",
            new=AsyncMock(return_value=_AVAILABILITY),
        ):
            return self.client.get("/metrics")

    def test_metrics_unauthenticated_and_prometheus_format(self) -> None:
        response = self._get_metrics()
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response.headers["content-type"])
        body = response.text
        self.assertIn("# TYPE tool_router_deferrals_total counter", body)
        self.assertIn("http_request_duration_seconds_count", body)
        self.assertIn('layer_available{layer="ollama"} 1', body)
        self.assertIn('layer_available{layer="openrouter"} 0', body)

    def test_request_counter_increments(self) -> None:
        def _count(text: str) -> int:
            for line in text.splitlines():
                if line.startswith("http_request_duration_seconds_count"):
                    return int(float(line.split()[-1]))
            self.fail("request-count metric not found")

        first = _count(self._get_metrics().text)
        # Every request (including /health) flows through the middleware.
        self.client.get("/health/live")
        second = _count(self._get_metrics().text)
        self.assertGreater(second, first)

    def test_embed_probe_not_rerun_within_ttl(self) -> None:
        """Repeated /metrics scrapes within the TTL must not re-probe the embed model."""
        from app.core import health as health_module

        health_module._embed_probe_cache = (False, 0.0)
        old_enabled = settings.tool_router_enabled
        settings.tool_router_enabled = True
        try:
            with (
                patch(
                    "app.core.health._probe_ollama_server",
                    new=AsyncMock(return_value=True),
                ),
                patch(
                    "app.core.model_registry.probe_openrouter",
                    new=AsyncMock(return_value=False),
                ),
                patch("app.core.embeddings.probe_embed_model", return_value=True) as probe,
            ):
                self.assertEqual(self.client.get("/metrics").status_code, 200)
                self.assertEqual(self.client.get("/metrics").status_code, 200)
                self.assertEqual(probe.call_count, 1)
        finally:
            settings.tool_router_enabled = old_enabled
            health_module._embed_probe_cache = (False, 0.0)


if __name__ == "__main__":
    unittest.main()
