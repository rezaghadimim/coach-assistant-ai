# Architecture Decision Records

This directory contains Architecture Decision Records (ADRs) for the Coach Assistant AI project.
Each ADR captures a significant architectural or technical decision, its context, the options considered, and the rationale for the choice made.

## Index

| # | Title | Status |
|---|-------|--------|
| [0001](0001-local-llm-with-ollama.md) | Local LLM inference with Ollama | Accepted |
| [0002](0002-fastapi-web-framework.md) | FastAPI as the web framework | Accepted |
| [0003](0003-in-memory-rag-retrieval.md) | In-memory token-similarity RAG retrieval | Accepted |
| [0004](0004-sqlite-memory-persistence.md) | SQLite for session and memory persistence | Accepted |
| [0005](0005-openwebui-integration.md) | Open WebUI integration via OpenAI-compatible API | Accepted |
| [0006](0006-optional-openrouter-provider.md) | Optional cloud LLM provider via OpenRouter | Accepted |
| [0007](0007-ollama-embedding-tool-routing.md) | Ollama embeddings for tool routing | Accepted (extended by 0009) |
| [0008](0008-cross-encoder-rag-reranker.md) | Cross-encoder reranker for two-stage RAG retrieval | Accepted |
| [0009](0009-tool-routing-synonym-rerank-llm-fallback.md) | Tool routing overhaul — synonym lexicon, rerank, LLM fallback | Accepted |
| [0010](0010-llm-response-formatter.md) | Optional LLM formatting pass for human-friendly data replies | Accepted |
| [0011](0011-collection-video-knowledge.md) | Per-collection video knowledge, dual embed providers, two-phase coach retrieval | Accepted |
| [0012](0012-adr-process.md) | ADR process (when required, numbering, supersession) | Accepted |
| [0014](0014-test-execution-contract.md) | Test execution contract (offline pytest, env isolation, network guard) | Accepted |

## Process

When to write an ADR, how to number it, and how to mark supersession: **[ADR-0012](0012-adr-process.md)**.

## Template

```markdown
# ADR-XXXX: Title

**Date:** YYYY-MM-DD
**Status:** Proposed | Accepted | Deprecated | Superseded

## Context

What is the situation or problem that prompted this decision?

## Decision

What was decided?

## Consequences

What are the positive and negative outcomes of this decision?

## Alternatives Considered

What other options were evaluated and why were they not chosen?
```
