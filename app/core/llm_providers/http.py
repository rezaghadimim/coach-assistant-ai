"""Shared, pooled ``httpx.AsyncClient`` instances + bounded retry helper.

REL-04 — one reusable client per base URL (with connection keep-alive) instead
of constructing and tearing down a client on every LLM call, which paid full
TCP/TLS setup per request and churned sockets.

REL-05 — a small retry wrapper for transient provider failures (connection
errors, timeouts, HTTP 429/5xx) with exponential backoff + jitter. Other 4xx
are returned immediately (never retried).
"""

from __future__ import annotations

import asyncio
import random
import threading
from typing import Optional

import httpx

# One client per base URL. httpx pools connections internally, so reusing a
# single client keeps TCP/TLS connections alive across calls.
_clients: dict[str, httpx.AsyncClient] = {}
_lock = threading.Lock()

# Conservative pool sizing — enough concurrency for a single app instance
# without unbounded socket growth.
_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10)

# Status codes worth retrying: rate limiting + transient server errors.
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


def get_client(base_url: str, timeout: float) -> httpx.AsyncClient:
    """Return a shared client for ``base_url``, creating it on first use.

    The client is created lazily (inside the running event loop) and reused
    for the process lifetime; :func:`close_all` disposes them on shutdown.
    """
    client = _clients.get(base_url)
    if client is not None and not client.is_closed:
        return client
    with _lock:
        client = _clients.get(base_url)
        if client is None or client.is_closed:
            client = httpx.AsyncClient(
                base_url=base_url, timeout=timeout, limits=_LIMITS
            )
            _clients[base_url] = client
        return client


async def close_all() -> None:
    """Close every pooled client. Call once on application shutdown."""
    with _lock:
        clients = list(_clients.values())
        _clients.clear()
    for client in clients:
        try:
            await client.aclose()
        except Exception:  # pragma: no cover - best-effort cleanup
            pass


async def post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    json: dict,
    headers: Optional[dict] = None,
    max_attempts: int = 3,
    base_delay: float = 0.5,
) -> httpx.Response:
    """POST with bounded retry on transient failures.

    Retries connection errors, timeouts, and HTTP 429/5xx up to
    ``max_attempts`` times with exponential backoff + jitter. Non-retryable
    responses (e.g. 4xx other than 429) are returned immediately; the caller is
    responsible for ``raise_for_status()``. Re-raises the underlying exception
    if connection/timeout errors persist through the final attempt.
    """
    delay = base_delay
    for attempt in range(1, max_attempts + 1):
        try:
            if headers is None:
                response = await client.post(url, json=json)
            else:
                response = await client.post(url, json=json, headers=headers)
        except (httpx.ConnectError, httpx.TimeoutException):
            if attempt >= max_attempts:
                raise
        else:
            if response.status_code not in _RETRYABLE_STATUS or attempt >= max_attempts:
                return response
        await asyncio.sleep(delay + random.uniform(0, base_delay))
        delay *= 2
    raise RuntimeError("post_with_retry exhausted attempts without returning")
