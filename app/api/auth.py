"""API-key authentication dependency applied to every API router."""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Request

from app.core.config import settings


def _candidate_keys(request: Request) -> list[str]:
    """Extract presented credentials from `X-API-Key` or `Authorization: Bearer`."""
    keys: list[str] = []
    header = request.headers.get("x-api-key")
    if header:
        keys.append(header)
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        keys.append(token.strip())
    return keys


async def require_api_key(request: Request) -> None:
    """Reject the request unless it presents the configured API key.

    Fails closed: with no `API_KEY` configured, every request is rejected
    unless `DEBUG=true` (local development).
    """
    if settings.api_key:
        for candidate in _candidate_keys(request):
            if hmac.compare_digest(candidate, settings.api_key):
                return
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    if settings.debug:
        return
    raise HTTPException(
        status_code=401,
        detail="API key not configured — set API_KEY (or DEBUG=true for local dev)",
    )
