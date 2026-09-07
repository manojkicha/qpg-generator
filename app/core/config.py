"""Configuration for the Question Paper Generator using pydantic-settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # ─── LLM Provider Selection ────────────────────────────────────────────────
    # Set to "ollama" or "openai" (or "azure_openai")
    llm_provider: str = "ollama"

    # ─── Ollama Settings ───────────────────────────────────────────────────────
    ollama_base_url: str = "http://localhost:11434"
    # Use a general-purpose (non-code-specialized) model for question generation.
    # Code-specialized models tend to over-format and under-emphasize pedagogy.
    ollama_model: str = "llama3:8b"
    ollama_temperature: float = 0.7

    # ─── OpenAI / Azure OpenAI Settings ────────────────────────────────────────
    # For OpenAI: set openai_api_key
    # For Azure OpenAI: set azure_* fields
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_base_url: str = ""  # Optional: custom OpenAI-compatible base URL

    # Azure OpenAI
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = "gpt-4o"
    azure_openai_embedding_deployment: str = "text-embedding-3-small"
    azure_openai_api_version: str = "2024-02-01"

    # ─── Embedding Settings ────────────────────────────────────────────────────
    # Set to "ollama" (for local embeddings) or "openai"
    embedding_provider: str = "ollama"
    openai_embedding_model: str = "text-embedding-3-small"

    # ─── Azure Document Intelligence ───────────────────────────────────────────
    azure_doc_intel_endpoint: str = ""
    azure_doc_intel_key: str = ""

    # ─── Vector Store Provider Selection ───────────────────────────────────────
    # Set to "local" (default — in-memory, no setup), "qdrant", or "azure_ai_search".
    # See app/services/vector_store/ — this is the only switch needed to move
    # between backends; no code changes required.
    vector_store_provider: str = "local"

    # ─── Azure AI Search ───────────────────────────────────────────────────────
    azure_search_endpoint: str = ""
    azure_search_key: str = ""
    azure_search_index: str = "question-paper-chunks"

    # ─── Qdrant ────────────────────────────────────────────────────────────────
    # Default matches the standard local Docker setup (dashboard at
    # http://localhost:6333/dashboard). Leave qdrant_api_key empty for a local
    # instance; set it when pointing at Qdrant Cloud or an auth-enabled instance.
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "question-paper-chunks"

    # ─── Azure Blob Storage ────────────────────────────────────────────────────
    azure_storage_connection_string: str = ""
    azure_blob_container: str = "source-documents"

    # ─── Database ──────────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./data/question_paper.db"
    redis_url: str = "redis://localhost:6379/0"

    # ─── Langfuse ──────────────────────────────────────────────────────────────
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # ─── MLflow ────────────────────────────────────────────────────────────────
    mlflow_tracking_uri: str = "http://localhost:5000"

    # ─── Application ────────────────────────────────────────────────────────────
    environment: str = "development"
    log_level: str = "INFO"


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()


settings = get_settings()