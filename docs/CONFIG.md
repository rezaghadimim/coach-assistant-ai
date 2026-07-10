# Configuration reference (env vars)

Source of truth: `app/core/config.py`. This file is a rendered reference — when they disagree, `config.py` wins; fix this file.

Generated from 88 `Settings` fields. Env names are the uppercased field name unless noted.

## App

| Field | Env | Default | Meaning |
|-------|-----|---------|---------|
| `app_name` | `APP_NAME` | `'Coach Assistant AI'` | Application display name |
| `app_version` | `APP_VERSION` | `'0.3.0'` | Application version string |

## Auth / Debug

| Field | Env | Default | Meaning |
|-------|-----|---------|---------|
| `api_key` | `API_KEY` | `''` | Shared API key (X-API-Key / Bearer); empty + debug=false → fail closed |
| `debug` | `DEBUG` | `False` | Dev mode: permits running without API key; never enable in production |

## LLM providers — Ollama

| Field | Env | Default | Meaning |
|-------|-----|---------|---------|
| `ollama_base_url` | `OLLAMA_BASE_URL` | `'http://localhost:11434'` | Ollama HTTP base URL |
| `ollama_model` | `OLLAMA_MODEL` | `'llama3.1:8b'` | Local chat model name |
| `ollama_timeout` | `OLLAMA_TIMEOUT` | `120.0` | Ollama request timeout (seconds) |
| `ollama_num_ctx` | `OLLAMA_NUM_CTX` | `8192` | Chat context window (tokens) sent to Ollama |
| `ollama_keep_alive` | `OLLAMA_KEEP_ALIVE` | `'30m'` | How long Ollama keeps the model loaded after a request |

## LLM providers — OpenAI-compatible

| Field | Env | Default | Meaning |
|-------|-----|---------|---------|
| `openai_api_key` | `OPENAI_API_KEY` | `''` | OpenAI / OpenAI-compatible API key (required for api.openai.com host) |
| `openai_base_url` | `OPENAI_BASE_URL` | `'https://api.openai.com/v1'` | OpenAI-compatible base URL (chat and/or embeddings) |
| `openai_model` | `OPENAI_MODEL` | `''` | When set, local/default LLM uses OpenAI-compatible provider instead of Ollama |
| `openai_timeout` | `OPENAI_TIMEOUT` | `120.0` | OpenAI-compatible request timeout (seconds) |
| `openai_frequency_penalty` | `OPENAI_FREQUENCY_PENALTY` | `0.4` | frequency_penalty on OpenAI-compatible chat requests |
| `openai_presence_penalty` | `OPENAI_PRESENCE_PENALTY` | `0.0` | presence_penalty on OpenAI-compatible chat requests |

## LLM providers — OpenRouter

| Field | Env | Default | Meaning |
|-------|-----|---------|---------|
| `openrouter_api_key` | `OPENROUTER_API_KEY` | `''` | OpenRouter API key; empty disables cloud provider |
| `openrouter_base_url` | `OPENROUTER_BASE_URL` | `'https://openrouter.ai/api/v1'` | OpenRouter API base URL |
| `openrouter_models` | `OPENROUTER_MODELS` | `'openai/gpt-4o-mini,openai/gpt-oss-120b:free,openai/gpt-os...'` | Comma-separated OpenRouter model IDs |
| `openrouter_timeout` | `OPENROUTER_TIMEOUT` | `120.0` | OpenRouter request timeout (seconds) |
| `openrouter_http_referer` | `OPENROUTER_HTTP_REFERER` | `''` | Optional HTTP-Referer header for OpenRouter |
| `openrouter_app_name` | `OPENROUTER_APP_NAME` | `'Coach Assistant AI'` | Optional X-Title / app name for OpenRouter |

## Temperatures & sampling

| Field | Env | Default | Meaning |
|-------|-----|---------|---------|
| `temperature_tool` | `TEMPERATURE_TOOL` | `0.0` | Temperature for tool-calling / LLM router / profile extraction |
| `temperature_grounded` | `TEMPERATURE_GROUNDED` | `0.0` | Temperature for RAG-grounded answers and data-reply formatting |
| `temperature_advice` | `TEMPERATURE_ADVICE` | `0.5` | Temperature for open coaching advice |
| `temperature` | `TEMPERATURE` | `0.5` | Legacy alias; defaults to temperature_advice |
| `max_tokens` | `MAX_TOKENS` | `1024` | Default max tokens for completions |
| `top_p` | `TOP_P` | `0.9` | Ollama top_p sampling |
| `repeat_penalty` | `REPEAT_PENALTY` | `1.1` | Ollama repeat_penalty |
| `max_tokens_classify` | `MAX_TOKENS_CLASSIFY` | `64` | Token budget for LLM-router classify calls |
| `max_tokens_formatter` | `MAX_TOKENS_FORMATTER` | `256` | Token budget for response-formatter LLM pass |

## Embeddings

| Field | Env | Default | Meaning |
|-------|-----|---------|---------|
| `rag_embed_provider` | `RAG_EMBED_PROVIDER` | `'ollama'` | Embed client protocol: ollama | openrouter | openai |
| `rag_embed_base_url` | `RAG_EMBED_BASE_URL` | `''` | Optional embed address override; empty reuses provider default |
| `rag_embed_model` | `RAG_EMBED_MODEL, ollama_embed_model, OLLAMA_EMBED_MODEL` | `'karuniaperjuangan/multilingual-e5-small'` | Embedding model id (aliases: OLLAMA_EMBED_MODEL) |
| `rag_collection_embed_provider` | `RAG_COLLECTION_EMBED_PROVIDER` | `None` | Optional override embed provider for collection corpus |
| `rag_collection_embed_model` | `RAG_COLLECTION_EMBED_MODEL` | `None` | Optional override embed model for collection corpus |

## RAG retrieval

| Field | Env | Default | Meaning |
|-------|-----|---------|---------|
| `rag_enabled` | `RAG_ENABLED` | `True` | Enable RAG context injection |
| `rag_knowledge_starter_dir` | `RAG_KNOWLEDGE_STARTER_DIR, rag_knowledge_templates_dir, RAG_KNOWLEDGE_TEMPLATES_DIR, rag_docs_dir, RAG_DOCS_DIR` | `'data/knowledge/starter'` | Bundled starter knowledge dir (aliases: RAG_DOCS_DIR, RAG_KNOWLEDGE_TEMPLATES_DIR) |
| `rag_knowledge_private_dir` | `RAG_KNOWLEDGE_PRIVATE_DIR` | `'data/knowledge/private'` | Private knowledge dir merged after starter |
| `rag_chunk_size` | `RAG_CHUNK_SIZE` | `300` | Chunk size (words) for ingest |
| `rag_chunk_overlap` | `RAG_CHUNK_OVERLAP` | `50` | Chunk overlap (words) |
| `rag_top_k` | `RAG_TOP_K` | `2` | Final top-k chunks after retrieval/rerank |
| `rag_min_score` | `RAG_MIN_SCORE` | `0.15` | Stage-1 candidate score floor |
| `rag_backend` | `RAG_BACKEND` | `'auto'` | embedding | token | auto |
| `rag_index_cache_path` | `RAG_INDEX_CACHE_PATH` | `'data/rag_index_cache.json'` | On-disk embedding cache path |
| `rag_retrieve_k` | `RAG_RETRIEVE_K` | `30` | Stage-1 candidate pool size before rerank |
| `rag_hybrid_rrf_enabled` | `RAG_HYBRID_RRF_ENABLED` | `True` | Merge embedding+token stage-1 via RRF |
| `rag_collections_dir` | `RAG_COLLECTIONS_DIR` | `'data/knowledge/collections'` | Public collections directory |
| `rag_collections_private_dir` | `RAG_COLLECTIONS_PRIVATE_DIR` | `'data/knowledge/private/collections'` | Private collections directory (submodule) |
| `rag_problem_top_k` | `RAG_PROBLEM_TOP_K` | `3` | Two-phase: situation/problem top-k |
| `rag_expert_top_k` | `RAG_EXPERT_TOP_K` | `6` | Two-phase: expert perspectives top-k |
| `rag_min_collections` | `RAG_MIN_COLLECTIONS` | `2` | Two-phase: minimum distinct collections |
| `rag_max_chunks_per_collection` | `RAG_MAX_CHUNKS_PER_COLLECTION` | `2` | Two-phase: cap chunks per collection |
| `rag_two_phase_enabled` | `RAG_TWO_PHASE_ENABLED` | `True` | Enable two-phase coach retrieval |
| `rag_attach_expert_ideas` | `RAG_ATTACH_EXPERT_IDEAS` | `True` | Attach deterministic expert-ideas section to answers |
| `rag_ideas_max` | `RAG_IDEAS_MAX` | `4` | Max expert ideas attached |
| `rag_ideas_excerpt_words` | `RAG_IDEAS_EXCERPT_WORDS` | `60` | Words per expert-idea excerpt |

## RAG rerank

| Field | Env | Default | Meaning |
|-------|-----|---------|---------|
| `rag_rerank_min_score` | `RAG_RERANK_MIN_SCORE` | `0.42` | Post-rerank score floor |
| `rag_rerank_enabled` | `RAG_RERANK_ENABLED` | `True` | Enable stage-2 cross-encoder rerank |
| `rag_rerank_model` | `RAG_RERANK_MODEL, ollama_rerank_model, OLLAMA_RERANK_MODEL` | `'BAAI/bge-reranker-base'` | Cross-encoder model id (aliases: OLLAMA_RERANK_MODEL) |
| `rag_rerank_batch_size` | `RAG_RERANK_BATCH_SIZE` | `32` | Passages per ONNX inference batch |
| `rag_rerank_max_passage_chars` | `RAG_RERANK_MAX_PASSAGE_CHARS` | `2000` | Max passage chars sent to reranker |
| `rag_rerank_provider` | `RAG_RERANK_PROVIDER` | `'local'` | local | tei (remote TEI /rerank) |
| `rag_rerank_base_url` | `RAG_RERANK_BASE_URL` | `''` | Remote rerank base URL when provider=tei |
| `rag_rerank_timeout` | `RAG_RERANK_TIMEOUT` | `30.0` | Remote rerank timeout (seconds) |
| `rag_rerank_cache_dir` | `RAG_RERANK_CACHE_DIR` | `'data/rerank_cache'` | fastembed model cache directory |

## Tool router

| Field | Env | Default | Meaning |
|-------|-----|---------|---------|
| `tool_router_enabled` | `TOOL_ROUTER_ENABLED` | `True` | Enable deterministic tool router |
| `tool_router_backend` | `TOOL_ROUTER_BACKEND` | `'auto'` | embedding | token | auto |
| `tool_knowledge_dir` | `TOOL_KNOWLEDGE_DIR` | `'data/tool-knowledge'` | Tool cards + routing corpus directory |
| `tool_router_threshold` | `TOOL_ROUTER_THRESHOLD` | `0.45` | Accept threshold for tool-router scores |
| `tool_router_margin` | `TOOL_ROUTER_MARGIN` | `0.08` | Min margin between top and runner-up |
| `tool_router_use_e5_prefix` | `TOOL_ROUTER_USE_E5_PREFIX` | `True` | Prepend E5 query/passage prefixes (also read by embed providers) |
| `tool_router_rerank_enabled` | `TOOL_ROUTER_RERANK_ENABLED` | `True` | Enable tool-router stage-2 cross-encoder |
| `tool_router_rerank_top_k` | `TOOL_ROUTER_RERANK_TOP_K` | `10` | Stage-1 pool size for tool-router rerank |
| `tool_router_embed_floor` | `TOOL_ROUTER_EMBED_FLOOR` | `0.3` | Stage-1 cosine floor before tool-router rerank |
| `tool_router_rerank_threshold` | `TOOL_ROUTER_RERANK_THRESHOLD` | `0.55` | Stage-2 accept threshold |
| `tool_router_rerank_margin` | `TOOL_ROUTER_RERANK_MARGIN` | `0.1` | Stage-2 margin between tools |
| `tool_router_rerank_model` | `TOOL_ROUTER_RERANK_MODEL` | `'BAAI/bge-reranker-base'` | Tool-router cross-encoder model (shares rag_rerank_cache_dir) |
| `tool_router_llm_fallback_enabled` | `TOOL_ROUTER_LLM_FALLBACK_ENABLED` | `True` | LLM JSON classify when fast path defers |
| `tool_router_near_miss_score` | `TOOL_ROUTER_NEAR_MISS_SCORE` | `0.25` | Near-miss observability threshold on deferral |
| `response_formatter_enabled` | `RESPONSE_FORMATTER_ENABLED` | `True` | Optional LLM pass for human-friendly data replies |

## Paths / media

| Field | Env | Default | Meaning |
|-------|-----|---------|---------|
| `media_root` | `MEDIA_ROOT` | `'data/media'` | Allowed root for local_media ingest paths |

## Timeouts

| Field | Env | Default | Meaning |
|-------|-----|---------|---------|
| `request_timeout_s` | `REQUEST_TIMEOUT_S` | `90.0` | Wall-clock budget for a single chat request (504 on exceed) |

## Memory / summary

| Field | Env | Default | Meaning |
|-------|-----|---------|---------|
| `memory_db_path` | `MEMORY_DB_PATH` | `'data/coach_assistant.db'` | SQLite path for memory + knowledge stores |
| `summary_trigger_messages` | `SUMMARY_TRIGGER_MESSAGES` | `20` | Message count before scheduling session summary |
| `summary_timeout_s` | `SUMMARY_TIMEOUT_S` | `90.0` | Ceiling for background summarization task |

## Observability

| Field | Env | Default | Meaning |
|-------|-----|---------|---------|
| `log_level` | `LOG_LEVEL` | `'INFO'` | Logging level |
| `log_step_payloads` | `LOG_STEP_PAYLOADS` | `False` | Include message text snippets in step logs (PII risk) |
| `log_error_file` | `LOG_ERROR_FILE` | `''` | Optional path for ERROR-level file logging |

## Gotchas

1. **`TOOL_ROUTER_USE_E5_PREFIX` is read by embed providers**, not only the tool router — `app/core/embed_providers/__init__.py:38` and `embed_providers/ollama.py:35` gate E5 `query:`/`passage:` prefixes from `settings.tool_router_use_e5_prefix`.
2. **Two rerank namespaces, one physical model.** `rag_rerank_*` and `tool_router_rerank_*` both drive cross-encoder scoring; tool router reuses `rag_rerank_cache_dir` (see `tool_router_rerank_model` comment in `config.py`).
3. **`rag_backend` values `auto` and `embedding` behave identically** in `_resolve_backend` (`app/rag/retriever.py:709-714`): both return whether the embedding index is ready; only `token` forces the token path.
4. **`OPENAI_MODEL` swaps the local provider class.** When `settings.openai_model` is set, `resolve_provider()` returns `OpenAIProvider` instead of `OllamaProvider` (`app/core/model_registry.py:82`).
5. **Legacy alias migration** in `_migrate_legacy_settings` (`config.py:301-328`): `OPENROUTER_MODEL` → `openrouter_models`; local Ollama-only reranker IDs remapped to `BAAI/bge-reranker-base`.
6. **Docker URL / path validators** (`config.py:334-377`): `host.docker.internal` → `localhost` when not in Docker; relative data paths resolved against project root.
