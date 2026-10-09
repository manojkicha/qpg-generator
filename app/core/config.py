"""Configuration for the Question Paper Generator using pydantic-settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # ─── LLM Provider Selection ────────────────────────────────────────────────
    # Set to "ollama" or "openai"
    llm_provider: str = "ollama"

    # ─── Ollama Settings ───────────────────────────────────────────────────────
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3:8b"
    ollama_temperature: float = 0.7
    ollama_embedding_model: str = "nomic-embed-text"

    # ─── OpenAI / Azure OpenAI Settings ────────────────────────────────────────
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_base_url: str = ""  # Optional: custom OpenAI-compatible base URL
    openai_embedding_model: str = "text-embedding-3-small"

    # Azure OpenAI
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = "gpt-4o"
    azure_openai_embedding_deployment: str = "text-embedding-3-small"
    azure_openai_api_version: str = "2024-08-01-preview"

    # ─── Embedding Settings ────────────────────────────────────────────────────
    # Set to "ollama" or "openai"
    embedding_provider: str = "ollama"

    # ─── Azure Document Intelligence ───────────────────────────────────────────
    azure_doc_intel_endpoint: str = ""
    azure_doc_intel_key: str = ""

    # ─── Vector Store Provider Selection ───────────────────────────────────────
    # Set to "local" (default — in-memory, no setup), "postgres", or "azure_ai_search".
    # See app/services/vector_store/ — this is the only switch needed to move
    # between backends; no code changes required.
    vector_store_provider: str = "local"

    # ─── Azure AI Search ───────────────────────────────────────────────────────
    azure_search_endpoint: str = ""
    azure_search_key: str = ""
    azure_search_index: str = "question-paper-chunks"

    # ─── PostgreSQL with pgvector ──────────────────────────────────────────────
    # Primary connection string (e.g. postgresql+asyncpg://user:password@host:5432/dbname).
    # If DATABASE_URL is set to a PostgreSQL URL, it is used directly.
    # Otherwise, individual settings below are assembled into a connection URL.
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "edusol_qpg"
    postgres_user: str = "postgres"
    postgres_password: str = ""
    postgres_ssl_mode: str = "prefer"

    # ─── Chroma DB ─────────────────────────────────────────────────────────────
    # Local embedded vector store — no separate service needed.
    chroma_collection: str = "question-paper-chunks"

    # ─── Azure Blob Storage ────────────────────────────────────────────────────
    azure_storage_connection_string: str = ""
    blob_connection_string: str = ""
    azure_blob_container: str = "source-documents"

    # ─── Database ──────────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///question_paper.db"
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
    secret_key: str



@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()


settings = get_settings()