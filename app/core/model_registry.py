"""Model registry: virtual model IDs, provider resolution, and cloud availability probe.

Open WebUI sees two virtual models when OpenRouter is healthy:
  - ``coach-assistant-ai``        → OllamaProvider (always available)
  - ``coach-assistant-ai-cloud``  → OpenRouterProvider (only when probe passes)

The cloud probe result is cached for 60 seconds to avoid hammering the
OpenRouter API on every /v1/models request.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Optional, Union

import httpx

from app.core.config import settings

if TYPE_CHECKING:
    from app.core.llm_providers.ollama import OllamaProvider
    from app.core.llm_providers.openrouter import OpenRouterProvider

logger = logging.getLogger(__name__)

LOCAL_MODEL_ID = "coach-assistant-ai"
CLOUD_MODEL_ID = "coach-assistant-ai-cloud"

_PROBE_TTL_SECONDS = 60
_PROBE_TIMEOUT_SECONDS = 5.0

# Module-level probe cache: (result, expires_at)
_probe_cache: tuple[bool, float] = (False, 0.0)


def _get_ollama_provider() -> "OllamaProvider":
    from app.core.llm_providers.ollama import OllamaProvider

    return OllamaProvider()


def _get_openrouter_provider() -> "OpenRouterProvider":
    from app.core.llm_providers.openrouter import OpenRouterProvider

    return OpenRouterProvider()


def resolve_provider(
    model_id: Optional[str],
) -> Union["OllamaProvider", "OpenRouterProvider"]:
    """Return the provider for the given virtual model ID.

    Unknown or None model IDs fall back to the local Ollama provider.
    The cloud provider is returned only when the API key is configured;
    no live probe is done here (that is done by list_available_models).
    """
    if model_id == CLOUD_MODEL_ID and settings.openrouter_api_key:
        return _get_openrouter_provider()
    return _get_ollama_provider()


async def probe_openrouter() -> bool:
    """Check whether OpenRouter is reachable and the API key is valid.

    Uses the cached result when it is still fresh. Returns False immediately
    when no API key is configured.
    """
    global _probe_cache

    if not settings.openrouter_api_key:
        return False

    cached_result, expires_at = _probe_cache
    if time.monotonic() < expires_at:
        return cached_result

    result = await _live_probe()
    _probe_cache = (result, time.monotonic() + _PROBE_TTL_SECONDS)
    return result


async def _live_probe() -> bool:
    """Perform a lightweight GET /auth/key request against OpenRouter."""
    try:
        async with httpx.AsyncClient(
            base_url=settings.openrouter_base_url,
            timeout=_PROBE_TIMEOUT_SECONDS,
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
            },
        ) as client:
            response = await client.get("/auth/key")
            ok = response.status_code < 400
            if not ok:
                logger.warning(
                    "OpenRouter probe returned HTTP %d", response.status_code
                )
            return ok
    except Exception as exc:
        logger.warning("OpenRouter probe failed: %s", exc)
        return False


async def list_available_models() -> list[dict]:
    """Return the list of virtual models to expose via /v1/models.

    Always includes the local model. Appends the cloud model only when the
    OpenRouter probe succeeds.
    """
    created_ts = int(time.time())

    models = [
        {
            "id": LOCAL_MODEL_ID,
            "object": "model",
            "created": created_ts,
            "owned_by": "coach-assistant-ai",
            "name": f"Coach Assistant AI (Local · {settings.ollama_model})",
        }
    ]

    cloud_available = await probe_openrouter()
    if cloud_available:
        models.append(
            {
                "id": CLOUD_MODEL_ID,
                "object": "model",
                "created": created_ts,
                "owned_by": "openrouter",
                "name": f"Coach Assistant AI (Cloud · {settings.openrouter_model})",
            }
        )

    return models


def openrouter_availability_reason() -> str:
    """Return a short reason string for why OpenRouter is unavailable (for /health)."""
    if not settings.openrouter_api_key:
        return "api_key_missing"
    # If we have a key but the last probe failed the cache will hold False.
    cached_result, expires_at = _probe_cache
    if time.monotonic() < expires_at and not cached_result:
        return "probe_failed"
    return "unknown"
