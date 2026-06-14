from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings

DEFAULT_OPENROUTER_MODELS = (
    "openai/gpt-4o-mini,"
    "openai/gpt-oss-120b:free,"
    "openai/gpt-oss-20b:free"
)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    app_name: str = "Coach Assistant AI"
    app_version: str = "0.3.0"

    # Ollama (local provider)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    ollama_timeout: float = 120.0

    # OpenRouter (optional cloud provider — leave api_key empty to disable)
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_models: str = DEFAULT_OPENROUTER_MODELS
    openrouter_timeout: float = 120.0
    openrouter_http_referer: str = ""
    openrouter_app_name: str = "Coach Assistant AI"

    # Generation parameters
    temperature: float = 0.7
    max_tokens: int = 1024

    # RAG
    rag_enabled: bool = True
    rag_docs_dir: str = "docs/knowledge"
    # Sized for E5-small (512 subword tokens; ~300 whitespace words is safe).
    rag_chunk_size: int = 300
    rag_chunk_overlap: int = 50
    rag_top_k: int = 3
    rag_min_score: float = 0.05
    # backend: "embedding" | "token" | "auto"
    # "auto" uses E5 embedding when the embed model probe passes, else falls back to token cosine.
    rag_backend: str = "auto"
    # On-disk cache for chunk embeddings so restarts don't re-embed unchanged content.
    rag_index_cache_path: str = "data/rag_index_cache.json"
    # Stage-1 candidate pool — retrieve this many chunks before reranking, then trim to rag_top_k.
    rag_retrieve_k: int = 25
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

    # Tool Router
    tool_router_enabled: bool = True
    # backend: "embedding" | "token" | "auto"
    # "auto" uses embedding when the Ollama embed model probe passes, else falls back to token.
    tool_router_backend: str = "auto"
    ollama_embed_model: str = "karuniaperjuangan/multilingual-e5-small"
    tool_knowledge_dir: str = "docs/tool-knowledge"
    tool_router_threshold: float = 0.75
    tool_router_margin: float = 0.08
    # Prepend "query: " / "passage: " prefixes required by multilingual-e5 models.
    tool_router_use_e5_prefix: bool = True

    # Memory
    memory_db_path: str = "data/coach_assistant.db"
    summary_trigger_messages: int = 20

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
        return self

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
