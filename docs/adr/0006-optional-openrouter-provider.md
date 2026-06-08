# ADR-0006: Optional Cloud LLM Provider via OpenRouter

**Date:** 2026-06-08
**Status:** Accepted

## Context

The project uses Ollama with Llama 3.1 8B locally (ADR-0001). Local inference
is private, free, and offline-capable but limited in model quality. There is a
need to:

- Test behaviour with larger, more capable models (e.g. GPT-4o-mini, Claude 3.5
  Sonnet) without replacing the local setup.
- Compare coaching response quality between the local model and cloud models.
- Give coaches running the stack in environments with a GPU the choice of a
  cloud fallback when local latency is too high.

A second provider must not break the existing local-only configuration —
operators who never set a cloud API key must see no change in behaviour.

## Decision

Add **OpenRouter** as an optional second LLM provider accessed via a thin
OpenAI-compatible HTTP client (`app/core/llm_providers/openrouter.py`).

Key design choices:

1. **Opt-in by API key**: setting `OPENROUTER_API_KEY` activates the cloud
   model; omitting it keeps the system fully local with no code change needed.

2. **Two virtual model IDs** in the OpenAI-compat layer:
   - `coach-assistant-ai` → Ollama (always available)
   - `coach-assistant-ai-cloud` → OpenRouter (only when probe passes)

3. **Live availability probe with 60-second TTL cache**: `GET /auth/key` is
   called at most once per minute to verify the key and network access. On
   failure the cloud model is hidden from `/v1/models` entirely — Open WebUI
   will not offer it as a choice.

4. **Local model stays the default**: `DEFAULT_MODELS: "coach-assistant-ai"` in
   docker-compose keeps Open WebUI pointing to Ollama out of the box even when
   both models are listed.

5. **Provider abstraction**: `app/core/llm_providers/` introduces `OllamaProvider`
   and `OpenRouterProvider` both satisfying the `LLMProvider` protocol. The
   agentic tool-calling loop in `llm.py` is provider-agnostic; providers handle
   their own message format differences (Ollama uses `tool_name`, OpenRouter
   uses `tool_call_id`).

6. **No new dependencies**: OpenRouter's API is OpenAI-compatible and reached
   with the already-present `httpx` library.

## Consequences

**Positive:**
- Coaches can compare local vs. cloud model quality by switching the model in
  the Open WebUI picker.
- Expensive cloud models are only used intentionally (not by default).
- The local-only configuration is entirely unchanged for operators who do not
  set `OPENROUTER_API_KEY`.
- Tool calling, RAG, memory, and scope guard all work through the provider
  abstraction with no behaviour change.

**Negative:**
- Cloud requests send conversation content to OpenRouter (and the underlying
  model provider). Coaches must be aware of this when handling sensitive data.
- OpenRouter incurs per-token costs. No in-app usage tracking is provided.
- The probe adds a short network round-trip on the first `/v1/models` or
  `/health` call after the 60-second TTL expires.

## Alternatives Considered

| Option | Reason Not Chosen |
|--------|------------------|
| LiteLLM as a unified gateway | Adds a new framework dependency and a separate process; overkill for two providers |
| Direct OpenAI or Anthropic SDK | Ties the code to a single vendor; OpenRouter lets us switch models without code changes |
| Environment flag `USE_CLOUD=true` | Less dynamic than the probe-based model; would require a restart to switch mid-session |
| Containerised Ollama service | Out of scope for this change; the stack already expects a host Ollama instance |
