# ADR-0002: FastAPI as the Web Framework

**Date:** 2024-01-01 (backfilled placeholder — written retroactively; see ADR-0006 onward for dated records)
**Status:** Accepted

## Context

The project needs a Python web framework to expose the coaching logic as a REST API. Requirements are:

- Async support — Ollama calls are inherently async (streaming responses, network I/O).
- Schema validation — requests and responses must be validated to catch integration errors early.
- Low boilerplate — the project scope is small; heavy frameworks add unnecessary complexity.
- OpenAPI documentation — auto-generated docs help during development and testing.
- Wide community adoption and active maintenance.

## Decision

Use **FastAPI** with **Pydantic v2** for request/response schema validation.

## Consequences

**Positive:**
- Native `async`/`await` support matches the Ollama streaming model.
- Pydantic models enforce schema contracts at the API boundary.
- Auto-generated `/docs` (Swagger UI) and `/redoc` with zero extra code.
- Lightweight — production dependencies are `fastapi`, `uvicorn`, and `pydantic`.
- `TestClient` (via Starlette) makes unit-testing endpoints straightforward.

**Negative:**
- Async programming model requires care around blocking calls (e.g., SQLite).
- Pydantic v2's stricter typing can require more explicit field definitions.

## Alternatives Considered

| Option | Reason Not Chosen |
|--------|------------------|
| Flask | Synchronous by default; requires additional effort for async streaming |
| Django REST Framework | Too heavyweight for a single-service API; ORM not needed |
| Starlette (bare) | FastAPI is Starlette with batteries; no benefit to dropping the layer |
| aiohttp | Less ergonomic for REST APIs; no built-in schema validation |
