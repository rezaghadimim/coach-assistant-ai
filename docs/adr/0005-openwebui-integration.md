# ADR-0005: Open WebUI Integration via OpenAI-Compatible API

**Date:** 2024-01-01 (backfilled placeholder — written retroactively; see ADR-0006 onward for dated records)
**Status:** Accepted

## Context

Phase 4 requires a web-based chat interface so users can interact with Coach Assistant AI without using `curl` or writing API clients. Requirements:

- Provides a polished, production-quality chat UI with minimal custom front-end code.
- Supports streaming responses for a responsive feel.
- Preserves all existing coaching features: RAG, session memory, and system prompt enrichment.
- Runs locally alongside the FastAPI backend.
- Compatible with the chosen LLM infrastructure (Ollama + local model).

## Decision

Integrate **Open WebUI** as the front-end by exposing an **OpenAI-compatible API layer** (`GET /v1/models`, `POST /v1/chat/completions`) in the FastAPI backend. Open WebUI is configured to connect to this endpoint instead of Ollama directly.

The full stack is orchestrated with **Docker Compose**: Open WebUI on port 3000, the Coach Assistant API on port 8000.

User sessions are identified via the `user` request field or an `X-User-Id` HTTP header, falling back to a shared `"openwebui-user"` session.

## Consequences

**Positive:**
- Zero custom front-end code — Open WebUI provides the full chat UI out of the box.
- The backend retains full control over the system prompt, RAG injection, and session memory.
- Streaming SSE is handled natively by Open WebUI.
- Any OpenAI-compatible client (LiteLLM, Continue.dev, custom apps) can also connect to `/v1/chat/completions`.
- Docker Compose provides a one-command deployment.

**Negative:**
- The coaching session user identity must be threaded through via a custom header or request field, since Open WebUI does not natively pass a user ID to the backend.
- Open WebUI also maintains its own conversation history display, which may diverge from the backend's SQLite history if the session is reset on one side.
- Docker image for Open WebUI is ~1 GB; not ideal for the most resource-constrained machines.

## Alternatives Considered

| Option | Reason Not Chosen |
|--------|------------------|
| Custom React/Vue front-end | Requires significant front-end development effort outside the project's current scope |
| Open WebUI **Pipe function** | More complex to configure; the OpenAI-compat layer is simpler and more reusable |
| Chainlit | Good Python-native UI, but less feature-complete than Open WebUI for coaching use cases |
| Gradio | Rapid prototyping tool; not designed for production chat sessions with memory |
| Direct Ollama connection in Open WebUI | Bypasses all coaching logic (RAG, memory, system prompt); not viable |
