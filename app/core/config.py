from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_OPENROUTER_MODELS = (
    "openai/gpt-4o-mini,"
    "openai/gpt-oss-120b:free,"
    "openai/gpt-oss-20b:free"
)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Coach Assistant AI"
    app_version: str = "0.3.0"

    # Ollama (local provider)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    ollama_timeout: float = 120.0

    # OpenAI (optional — direct embeddings when rag_*_embed_provider=openai)
    openai_api_key: str = ""

    # OpenRouter (optional cloud provider — leave api_key empty to disable)
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_models: str = DEFAULT_OPENROUTER_MODELS
    openrouter_timeout: float = 120.0
    openrouter_http_referer: str = ""
    openrouter_app_name: str = "Coach Assistant AI"

    # Generation parameters
    # Per-task temperatures: keep low for deterministic tasks, higher only for free-form advice.
    temperature_tool: float = 0.0       # Tool-calling loop, LLM router, profile extraction
    temperature_grounded: float = 0.0   # RAG-grounded answers, data reply formatting
    temperature_advice: float = 0.5     # Open coaching advice (free-form prose)
    # Legacy alias kept for external callers / env var compatibility.
    # Defaults to temperature_advice; overridden per-call by the task-specific settings above.
    temperature: float = 0.5
    max_tokens: int = 1024
    # Sampling options applied to all Ollama completions.
    top_p: float = 0.9
    repeat_penalty: float = 1.1
    # Reduced token budget for single-purpose classify calls (LLM router).
    max_tokens_classify: int = 64
    # Token budget for the optional response-formatter LLM pass (tables need more room).
    max_tokens_formatter: int = 256

    # RAG
    rag_enabled: bool = True
    # Committed starter / bundled knowledge (safe to git). Indexed on every ingest.
    rag_knowledge_starter_dir: str = Field(
        default="docs/knowledge/starter",
        validation_alias=AliasChoices(
            "rag_knowledge_starter_dir",
            "RAG_KNOWLEDGE_STARTER_DIR",
            # Legacy names map to starter.
            "rag_knowledge_templates_dir",
            "RAG_KNOWLEDGE_TEMPLATES_DIR",
            "rag_docs_dir",
            "RAG_DOCS_DIR",
        ),
    )
    # Local-only content (private git repo). Merged after starter on ingest.
    # Files with the same relative path override the starter copy.
    rag_knowledge_private_dir: str = Field(
        default="docs/knowledge/private",
        validation_alias=AliasChoices(
            "rag_knowledge_private_dir",
            "RAG_KNOWLEDGE_PRIVATE_DIR",
        ),
    )
    # Sized for E5-small (512 subword tokens; ~300 whitespace words is safe).
    rag_chunk_size: int = 300
    rag_chunk_overlap: int = 50
    rag_top_k: int = 2
    # Stage-1 candidate pool floor (bi-encoder / token cosine).  Kept low for recall.
    rag_min_score: float = 0.15
    # Final floor after cross-encoder reranking (sigmoid scores in 0–1).  Higher than
    # rag_min_score to abstain on off-topic queries that slip through stage-1.
    rag_rerank_min_score: float = 0.42
    # backend: "embedding" | "token" | "auto"
    # "auto" uses E5 embedding when the embed model probe passes, else falls back to token cosine.
    rag_backend: str = "auto"
    # On-disk cache for chunk embeddings so restarts don't re-embed unchanged content.
    rag_index_cache_path: str = "data/rag_index_cache.json"
    # Stage-1 candidate pool — retrieve this many chunks before reranking, then trim to rag_top_k.
    rag_retrieve_k: int = 30
    # Merge embedding + token stage-1 lists via RRF before reranking (improves exact-term recall).
    rag_hybrid_rrf_enabled: bool = True
    # Stage-2 cross-encoder reranker — runs locally in-process via fastembed (ONNX,
    # no PyTorch, no Ollama). Ollama cannot serve reranker models (ollama/ollama #3368).
    rag_rerank_enabled: bool = True
    # fastembed TextCrossEncoder model. See TextCrossEncoder.list_supported_models().
    rag_rerank_model: str = Field(
        default="BAAI/bge-reranker-base",
        validation_alias=AliasChoices(
            "rag_rerank_model",
            "RAG_RERANK_MODEL",
            # Back-compat with the previous Ollama-based reranker settings.
            "ollama_rerank_model",
            "OLLAMA_RERANK_MODEL",
        ),
    )
    # Passages scored per ONNX inference batch (correctness-neutral; tune for speed).
    rag_rerank_batch_size: int = 32
    rag_rerank_max_passage_chars: int = 2000
    # Where fastembed caches the downloaded reranker model. Kept under data/ so it
    # survives restarts (and lands in the mounted Docker volume) instead of /tmp.
    rag_rerank_cache_dir: str = "data/rerank_cache"
    # Embedding providers: ollama | openrouter | openai
    rag_embed_provider: str = "ollama"
    rag_embed_model: str = Field(
        default="karuniaperjuangan/multilingual-e5-small",
        validation_alias=AliasChoices("rag_embed_model", "RAG_EMBED_MODEL"),
    )
    rag_collection_embed_provider: str = "openrouter"
    rag_collection_embed_model: str = Field(
        default="openai/text-embedding-3-small",
        validation_alias=AliasChoices(
            "rag_collection_embed_model",
            "RAG_COLLECTION_EMBED_MODEL",
        ),
    )
    rag_collections_dir: str = Field(
        default="data/knowledge/collections",
        validation_alias=AliasChoices("rag_collections_dir", "RAG_COLLECTIONS_DIR"),
    )
    # Two-phase coach retrieval
    rag_problem_top_k: int = 3
    rag_expert_top_k: int = 6
    rag_min_collections: int = 2
    rag_max_chunks_per_collection: int = 2
    rag_two_phase_enabled: bool = True

    # Tool Router
    tool_router_enabled: bool = True
    # backend: "embedding" | "token" | "auto"
    # "auto" uses embedding when the Ollama embed model probe passes, else falls back to token.
    tool_router_backend: str = "auto"
    ollama_embed_model: str = "karuniaperjuangan/multilingual-e5-small"
    tool_knowledge_dir: str = "docs/tool-knowledge"
    # Tuned against 307-example corpus: threshold=0.65 yields 95.77% on the hard
    # eval set (up from 85.92% at 0.75) with precision=1.00 (no wrong-tool fires).
    tool_router_threshold: float = 0.65
    tool_router_margin: float = 0.08
    # Prepend "query: " / "passage: " prefixes required by multilingual-e5 models.
    tool_router_use_e5_prefix: bool = True
    # Two-stage rerank: stage-1 embedding recall -> stage-2 cross-encoder precision.
    # Runs only when both the embed model and fastembed cross-encoder are available.
    tool_router_rerank_enabled: bool = True
    # Stage-1 candidate pool size (how many embed-similar examples to pass to reranker).
    tool_router_rerank_top_k: int = 10
    # Low cosine floor for stage-1 to avoid scoring completely irrelevant candidates.
    tool_router_embed_floor: float = 0.30
    # Stage-2 sigmoid acceptance threshold (cross-encoder distribution differs from e5).
    tool_router_rerank_threshold: float = 0.55
    # Minimum margin between top and runner-up tool in cross-encoder scores.
    tool_router_rerank_margin: float = 0.10
    # Cross-encoder model reused from RAG; shares rag_rerank_cache_dir.
    tool_router_rerank_model: str = "BAAI/bge-reranker-base"
    # LLM router fallback: one constrained LLM call when all fast-path layers defer.
    tool_router_llm_fallback_enabled: bool = True
    # Near-miss threshold for deferral observability (top score >= this → near_miss).
    tool_router_near_miss_score: float = 0.25

    # Response Formatter: optional LLM pass for human-friendly data replies.
    # Enabled by default after benchmark on llama3.1:8b (PII 100%, ~686 ms overhead).
    # Disable with RESPONSE_FORMATTER_ENABLED=false to skip the extra LLM call.
    # Fast-path read results are rephrased by a compact LLM call (at
    # temperature_grounded=0) before being returned.  PII validation runs after
    # formatting; on failure the deterministic template is used instead.
    # Uses the same Ollama model as the main chat (ollama_model).
    response_formatter_enabled: bool = Field(
        default=True,
        description=(
            "Pass fast-path data replies through an LLM for human-friendly formatting. "
            "Disable with RESPONSE_FORMATTER_ENABLED=false."
        ),
    )

    # Memory
    memory_db_path: str = "data/coach_assistant.db"
    summary_trigger_messages: int = 20

    # Logging
    log_level: str = "INFO"
    # When True, message/reply text snippets are included in step logs.
    # Set to False to suppress content previews (e.g. for privacy).
    log_step_payloads: bool = True
    # Optional path for ERROR-level logs (e.g. /app/logs/errors.log in Docker Compose).
    # Leave empty to log to stdout only.
    log_error_file: str = ""

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_settings(cls, data: object) -> object:
        """Map legacy env keys to current names."""
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if not data.get("openrouter_models") and not data.get("OPENROUTER_MODELS"):
            legacy = data.get("openrouter_model") or data.get("OPENROUTER_MODEL")
            if legacy:
                data["openrouter_models"] = legacy
        rerank_model = (
            data.get("rag_rerank_model")
            or data.get("RAG_RERANK_MODEL")
            or data.get("ollama_rerank_model")
            or data.get("OLLAMA_RERANK_MODEL")
        )
        if isinstance(rerank_model, str):
            normalized = rerank_model.strip()
            # Ollama-only reranker IDs are not loadable via fastembed; map to the default.
            if normalized.startswith("dengcao/") or normalized.endswith("bge-reranker-v2-m3"):
                data["rag_rerank_model"] = "BAAI/bge-reranker-base"
        return data

    @staticmethod
    def _running_in_docker() -> bool:
        return Path("/.dockerenv").exists()

    @model_validator(mode="after")
    def _normalize_ollama_base_url(self) -> "Settings":
        """Map ``host.docker.internal`` to ``localhost`` when not inside Docker.

        ``.env.example`` defaults to the Docker Compose URL so containers can
        reach the host Ollama.  Native scripts and ``uvicorn`` on the machine
        should talk to ``localhost`` instead — ``host.docker.internal`` often
        does not resolve outside Docker Desktop.
        """
        if not self._running_in_docker() and "host.docker.internal" in self.ollama_base_url:
            self.ollama_base_url = self.ollama_base_url.replace(
                "host.docker.internal", "localhost"
            )
        return self

    @model_validator(mode="after")
    def _resolve_relative_paths(self) -> "Settings":
        """Resolve relative data paths to absolute using the project root.

        This ensures paths like ``data/rerank_cache`` behave the same whether
        the app is started from the project root, a sub-directory, or a test
        runner with a different CWD.  Absolute paths (e.g. the Docker env var
        ``RAG_RERANK_CACHE_DIR=/app/data/rerank_cache``) are left unchanged.
        """
        # config.py lives at <project_root>/app/core/config.py
        project_root = Path(__file__).resolve().parent.parent.parent
        if self.rag_rerank_cache_dir and not Path(self.rag_rerank_cache_dir).is_absolute():
            self.rag_rerank_cache_dir = str(project_root / self.rag_rerank_cache_dir)
        if self.rag_collections_dir and not Path(self.rag_collections_dir).is_absolute():
            self.rag_collections_dir = str(project_root / self.rag_collections_dir)
        if self.rag_index_cache_path and not Path(self.rag_index_cache_path).is_absolute():
            self.rag_index_cache_path = str(project_root / self.rag_index_cache_path)
        if self.log_error_file and not Path(self.log_error_file).is_absolute():
            self.log_error_file = str(project_root / self.log_error_file)
        return self

settings = Settings()
