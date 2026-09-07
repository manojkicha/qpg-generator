"""Unified LLM client — supports Ollama, OpenAI, and Azure OpenAI via config.

Switch between providers by setting `LLM_PROVIDER` in your .env:
  - "ollama"      → local Ollama with qwen2.5-coder:14b (default)
  - "openai"      → OpenAI API
  - "azure_openai" → Azure OpenAI
"""

import logging
from typing import Any, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.embeddings import Embeddings
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_openai import ChatOpenAI, AzureChatOpenAI, OpenAIEmbeddings, AzureOpenAIEmbeddings

from app.core.config import settings

logger = logging.getLogger(__name__)


# ─── Chat Model ─────────────────────────────────────────────────────────────────

def get_chat_model(**kwargs) -> BaseChatModel:
    """Return the configured chat model based on LLM_PROVIDER."""
    provider = settings.llm_provider.lower()

    if provider == "ollama":
        return _get_ollama_chat(**kwargs)
    elif provider == "openai":
        return _get_openai_chat(**kwargs)
    elif provider == "azure_openai":
        return _get_azure_openai_chat(**kwargs)
    else:
        logger.warning("Unknown LLM provider '%s', defaulting to Ollama", provider)
        return _get_ollama_chat(**kwargs)


def _get_ollama_chat(**kwargs) -> ChatOllama:
    """Ollama chat model — local, no API key needed."""
    return ChatOllama(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        temperature=kwargs.get("temperature", settings.ollama_temperature),
        timeout=kwargs.get("timeout", 300),
        format=kwargs.get("format", "json"),  # JSON mode for structured output
    )


def _get_openai_chat(**kwargs) -> ChatOpenAI:
    """Standard OpenAI chat model."""
    return ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url or None,
        temperature=kwargs.get("temperature", 0.7),
    )


def _get_azure_openai_chat(**kwargs) -> AzureChatOpenAI:
    """Azure OpenAI chat model."""
    return AzureChatOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        azure_deployment=settings.azure_openai_deployment,
        api_version=settings.azure_openai_api_version,
        temperature=kwargs.get("temperature", 0.7),
    )


# ─── Embeddings ────────────────────────────────────────────────────────────────

def get_embeddings_model() -> Embeddings:
    """Return the configured embeddings model based on EMBEDDING_PROVIDER."""
    provider = settings.embedding_provider.lower()

    if provider == "ollama":
        return _get_ollama_embeddings()
    elif provider == "openai":
        return _get_openai_embeddings()
    elif provider == "azure_openai":
        return _get_azure_openai_embeddings()
    else:
        logger.warning("Unknown embedding provider '%s', defaulting to Ollama", provider)
        return _get_ollama_embeddings()


def _get_ollama_embeddings() -> OllamaEmbeddings:
    """Ollama embeddings — local, no API key needed."""
    return OllamaEmbeddings(
        base_url=settings.ollama_base_url,
        model="nomic-embed-text",  # Fast, high-quality local embeddings
    )


def _get_openai_embeddings() -> OpenAIEmbeddings:
    """Standard OpenAI embeddings."""
    return OpenAIEmbeddings(
        model=settings.openai_embedding_model,
        api_key=settings.openai_api_key,
    )


def _get_azure_openai_embeddings() -> AzureOpenAIEmbeddings:
    """Azure OpenAI embeddings."""
    return AzureOpenAIEmbeddings(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        azure_deployment=settings.azure_openai_embedding_deployment,
        api_version=settings.azure_openai_api_version,
    )


# ─── Convenience factory ────────────────────────────────────────────────────────

def create_llm_client(temperature: float = 0.7) -> tuple[BaseChatModel, Embeddings]:
    """Create both chat model and embeddings from config.

    Returns:
        Tuple of (chat_model, embeddings_model)
    """
    chat = get_chat_model(temperature=temperature)
    embeddings = get_embeddings_model()
    return chat, embeddings


# ─── Status / diagnostics ──────────────────────────────────────────────────────

def get_provider_info() -> dict[str, Any]:
    """Return info about the current provider for diagnostics."""
    return {
        "llm_provider": settings.llm_provider,
        "llm_model": (
            settings.ollama_model
            if settings.llm_provider == "ollama"
            else settings.openai_model
            if settings.llm_provider == "openai"
            else settings.azure_openai_deployment
        ),
        "ollama_base_url": settings.ollama_base_url,
        "embedding_provider": settings.embedding_provider,
    }