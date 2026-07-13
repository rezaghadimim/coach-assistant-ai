"""Deterministic test environment pins and fail-fast network guard.

Applied by ``tests/conftest.py`` before any test module imports ``app``.
The pin list is registered in ``docs/CONTRACTS.md`` and checked by
``scripts/check_contracts.py``.
"""

from __future__ import annotations

import os
import socket
from typing import Any

# Force-set before Settings() loads — overrides .env and shell exports.
TEST_ENV_OVERRIDES: dict[str, str] = {
    "DEBUG": "true",
    "RAG_BACKEND": "token",
    "TOOL_ROUTER_BACKEND": "token",
    "RESPONSE_FORMATTER_ENABLED": "false",
    "RAG_RERANK_ENABLED": "false",
    "RAG_EMBED_PROVIDER": "ollama",
    "RAG_EMBED_BASE_URL": "",
    "RAG_COLLECTION_EMBED_PROVIDER": "",
    "RAG_COLLECTION_EMBED_MODEL": "",
    "RAG_RERANK_PROVIDER": "local",
    "RAG_RERANK_BASE_URL": "",
    "OPENAI_API_KEY": "",
    "OPENAI_MODEL": "",
    "OPENROUTER_API_KEY": "",
    "OLLAMA_BASE_URL": "http://127.0.0.1:1",
    "OPENAI_BASE_URL": "http://127.0.0.1:1",
    "OPENROUTER_BASE_URL": "http://127.0.0.1:1",
}

_NETWORK_VIOLATION = (
    "Test Execution Contract violation: unexpected outbound network access "
    "to {address!r}. Automated tests must be offline by default — mock external "
    "services or set RUN_LLM_ROUTER_INTEGRATION=1 / RUN_RERANK_INTEGRATION=1 "
    "for opt-in live integration. See docs/TEST_EXECUTION.md."
)

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "0.0.0.0", ""})

_original_socket_connect = socket.socket.connect


def apply_env_overrides() -> None:
    """Force deterministic test env — overrides developer .env values."""
    for key, value in TEST_ENV_OVERRIDES.items():
        os.environ[key] = value


def apply_settings_overrides(settings: object) -> None:
    """Re-sync the settings singleton after import (belt-and-suspenders)."""
    # Typed as object to avoid importing Settings before env pins are applied.
    settings.debug = True  # type: ignore[attr-defined]
    settings.rag_backend = "token"  # type: ignore[attr-defined]
    settings.tool_router_backend = "token"  # type: ignore[attr-defined]
    settings.response_formatter_enabled = False  # type: ignore[attr-defined]
    settings.rag_rerank_enabled = False  # type: ignore[attr-defined]
    settings.rag_embed_provider = "ollama"  # type: ignore[attr-defined]
    settings.rag_embed_base_url = ""  # type: ignore[attr-defined]
    settings.rag_collection_embed_provider = None  # type: ignore[attr-defined]
    settings.rag_collection_embed_model = None  # type: ignore[attr-defined]
    settings.rag_rerank_provider = "local"  # type: ignore[attr-defined]
    settings.rag_rerank_base_url = ""  # type: ignore[attr-defined]
    settings.openai_api_key = ""  # type: ignore[attr-defined]
    settings.openai_model = ""  # type: ignore[attr-defined]
    settings.openai_base_url = "http://127.0.0.1:1"  # type: ignore[attr-defined]
    settings.openrouter_api_key = ""  # type: ignore[attr-defined]
    settings.openrouter_base_url = "http://127.0.0.1:1"  # type: ignore[attr-defined]
    settings.ollama_base_url = "http://127.0.0.1:1"  # type: ignore[attr-defined]


def _external_network_opt_in() -> bool:
    for key in ("RUN_LLM_ROUTER_INTEGRATION", "RUN_RERANK_INTEGRATION"):
        if os.environ.get(key, "").lower() in {"1", "true", "yes"}:
            return True
    return False


def _host_from_address(address: Any) -> str | None:
    if isinstance(address, tuple) and address:
        return str(address[0])
    if isinstance(address, str):
        return address.split(":")[0] if ":" in address else address
    return None


def _is_allowed_host(host: str | None) -> bool:
    if host is None:
        return True
    normalized = host.lower()
    if normalized in _LOOPBACK_HOSTS:
        return True
    if normalized.endswith(".localhost"):
        return True
    return False


def _guarded_socket_connect(self: socket.socket, address: Any) -> Any:
    if _external_network_opt_in():
        return _original_socket_connect(self, address)
    host = _host_from_address(address)
    if _is_allowed_host(host):
        return _original_socket_connect(self, address)
    raise RuntimeError(_NETWORK_VIOLATION.format(address=address))


def install_network_guard() -> None:
    socket.socket.connect = _guarded_socket_connect  # type: ignore[method-assign]


def uninstall_network_guard() -> None:
    socket.socket.connect = _original_socket_connect  # type: ignore[method-assign]


def reset_rerank_probe_cache() -> None:
    """Clear module-level rerank probe state polluted by app lifespan or probe tests."""
    import app.core.rerank as rerank_mod

    rerank_mod._probe_ok = None
    rerank_mod._encoder = None
    rerank_mod._encoder_model_name = None
