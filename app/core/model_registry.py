"""Model registry: virtual model IDs, provider resolution, and cloud availability probe.

Open WebUI sees the local model plus cloud models when OpenRouter is healthy.
Cloud models are configured via the comma-separated ``OPENROUTER_MODELS`` env var.
The first slug maps to ``coach-assistant-ai-cloud``; additional slugs get derived
virtual IDs (e.g. ``coach-assistant-ai-cloud-gpt-oss-120b``).

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
    from app.core.llm_providers.openai_compat import OpenAIProvider
    from app.core.llm_providers.openrouter import OpenRouterProvider

logger = logging.getLogger(__name__)

LOCAL_MODEL_ID = "coach-assistant-ai"
# Explicit Ollama selection. Exposed as its own virtual model only when
# openai_model is also set — otherwise LOCAL_MODEL_ID already means Ollama,
# and a second entry for the same backend would just clutter the picker.
LOCAL_OLLAMA_MODEL_ID = "coach-assistant-ai-ollama"
CLOUD_MODEL_ID = "coach-assistant-ai-cloud"


def _parse_openrouter_model_slugs(raw: str) -> list[str]:
    return [slug.strip() for slug in raw.split(",") if slug.strip()]


def _virtual_id_for_slug(slug: str, *, primary: bool) -> str:
    if primary:
        return CLOUD_MODEL_ID
    name = slug.rsplit("/", 1)[-1]
    name = name.split(":", 1)[0]
    return f"coach-assistant-ai-cloud-{name.replace('.', '-')}"


def openrouter_models() -> dict[str, str]:
    """Return virtual cloud model IDs mapped to OpenRouter model slugs."""
    slugs = _parse_openrouter_model_slugs(settings.openrouter_models)
    registry: dict[str, str] = {}
    for index, slug in enumerate(slugs):
        virtual_id = _virtual_id_for_slug(slug, primary=index == 0)
        registry[virtual_id] = slug
    return registry


def is_cloud_model_id(model_id: Optional[str]) -> bool:
    """Return True when ``model_id`` routes to OpenRouter."""
    return model_id is not None and model_id in openrouter_models()


def is_ollama_model_id(model_id: Optional[str]) -> bool:
    """Return True when ``model_id`` explicitly requests the Ollama backend."""
    return model_id == LOCAL_OLLAMA_MODEL_ID


_PROBE_TTL_SECONDS = 60
_PROBE_TIMEOUT_SECONDS = 5.0

# Module-level probe cache: (result, expires_at)
_probe_cache: tuple[bool, float] = (False, 0.0)


def get_local_provider() -> Union["OllamaProvider", "OpenAIProvider"]:
    """Return the local/default chat provider.

    Uses the OpenAI-compatible provider when ``openai_model`` is configured
    (e.g. a self-hosted vLLM/TGI server), else falls back to Ollama.
    """
    if settings.openai_model:
        from app.core.llm_providers.openai_compat import OpenAIProvider

        return OpenAIProvider()

    from app.core.llm_providers.ollama import OllamaProvider

    return OllamaProvider()


def resolve_provider(
    model_id: Optional[str],
) -> Union["OllamaProvider", "OpenAIProvider", "OpenRouterProvider"]:
    """Return the provider for the given virtual model ID.

    Unknown or None model IDs fall back to the local provider (see
    ``get_local_provider``). The cloud provider is returned only when the
    API key is configured; no live probe is done here (that is done by
    list_available_models). ``LOCAL_OLLAMA_MODEL_ID`` always resolves to
    Ollama explicitly, even when ``openai_model`` is set and would otherwise
    make ``get_local_provider`` pick the OpenAI-compatible backend.
    """
    if is_cloud_model_id(model_id) and settings.openrouter_api_key:
        from app.core.llm_providers.openrouter import OpenRouterProvider

        return OpenRouterProvider(model=openrouter_models()[model_id])
    if is_ollama_model_id(model_id):
        from app.core.llm_providers.ollama import OllamaProvider

        return OllamaProvider()
    return get_local_provider()


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

    local_model_name = settings.openai_model or settings.ollama_model
    models = [
        {
            "id": LOCAL_MODEL_ID,
            "object": "model",
            "created": created_ts,
            "owned_by": "coach-assistant-ai",
            "name": f"Coach Assistant AI (Local · {local_model_name})",
        }
    ]

    # get_local_provider() picks OpenAI-compat over Ollama whenever
    # openai_model is set, which would otherwise make Ollama unreachable
    # through LOCAL_MODEL_ID even though it's still configured and running.
    # Surface it as its own entry so both stay selectable.
    if settings.openai_model:
        models.append(
            {
                "id": LOCAL_OLLAMA_MODEL_ID,
                "object": "model",
                "created": created_ts,
                "owned_by": "coach-assistant-ai",
                "name": f"Coach Assistant AI (Local · Ollama {settings.ollama_model})",
            }
        )

    cloud_available = await probe_openrouter()
    if cloud_available:
        for virtual_id, openrouter_slug in openrouter_models().items():
            models.append(
                {
                    "id": virtual_id,
                    "object": "model",
                    "created": created_ts,
                    "owned_by": "openrouter",
                    "name": f"Coach Assistant AI (Cloud · {openrouter_slug})",
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
