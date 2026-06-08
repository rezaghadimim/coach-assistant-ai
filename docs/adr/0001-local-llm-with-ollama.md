# ADR-0001: Local LLM Inference with Ollama

**Date:** 2024-01-01
**Status:** Accepted

## Context

The Coach Assistant AI project requires a language model for conversational coaching. Key requirements are:

- **Privacy**: Coaching conversations contain sensitive personal information and must not leave the user's machine.
- **Cost**: Cloud LLM APIs (OpenAI, Anthropic) incur per-token costs that compound over extended coaching sessions.
- **Offline capability**: Coaches and clients may not always have reliable internet access.
- **Customisability**: Future fine-tuning (Phase 5) requires direct model access.

## Decision

Use **Ollama** to run `llama3.1:8b` locally. The backend communicates with Ollama's REST API over `localhost`.

## Consequences

**Positive:**
- All conversation data stays on the user's machine — no third-party data exposure.
- Zero inference cost after the initial model download.
- Works offline.
- Compatible with future LoRA fine-tuning (Phase 5).

**Negative:**
- Requires a machine with sufficient RAM (≥8 GB) and ideally a GPU for acceptable response latency.
- Model quality is lower than the largest cloud-hosted models.
- Users must install and manage Ollama separately.

## Alternatives Considered

| Option | Reason Not Chosen |
|--------|------------------|
| OpenAI API (GPT-4) | Sends user data to a third party; per-token cost; no fine-tuning ownership |
| Hugging Face `transformers` direct | Significantly higher integration complexity; no simple model-serving interface |
| LM Studio | GUI-only; no stable REST API for programmatic integration |
