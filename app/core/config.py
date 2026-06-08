from pydantic_settings import BaseSettings


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
    openrouter_model: str = "openai/gpt-4o-mini"
    openrouter_timeout: float = 120.0
    openrouter_http_referer: str = ""
    openrouter_app_name: str = "Coach Assistant AI"

    # Generation parameters
    temperature: float = 0.7
    max_tokens: int = 1024

    # RAG
    rag_enabled: bool = True
    rag_docs_dir: str = "docs/knowledge"
    rag_chunk_size: int = 512
    rag_chunk_overlap: int = 50
    rag_top_k: int = 3
    rag_min_score: float = 0.05

    # Memory
    memory_db_path: str = "data/coach_assistant.db"
    summary_trigger_messages: int = 20

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
