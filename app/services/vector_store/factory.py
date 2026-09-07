"""Picks the vector store backend based on `VECTOR_STORE_PROVIDER`.

This is the single switch for the whole app — `IngestionService` and
`SearchService` both just call `get_vector_store()` and never import a
specific backend directly, so changing providers is a one-line .env edit,
not a code change.
"""

import logging

from app.core.config import settings

from .base import VectorStoreClient

logger = logging.getLogger(__name__)


def get_vector_store() -> VectorStoreClient:
    """Return the vector store configured via VECTOR_STORE_PROVIDER.

    Values:
      - "qdrant"          → Qdrant (QDRANT_URL, QDRANT_COLLECTION, QDRANT_API_KEY)
      - "azure_ai_search" → Azure AI Search (AZURE_SEARCH_ENDPOINT/KEY/INDEX)
      - "local" (default) → in-memory cosine similarity search, no external DB

    For backward compatibility with setups from before this setting existed:
    if the provider is left at its default ("local") but Azure AI Search
    credentials are present, Azure AI Search is used automatically.
    """
    provider = (settings.vector_store_provider or "local").strip().lower()

    if provider == "qdrant":
        from .qdrant_store import QdrantStore

        logger.info("Vector store: Qdrant (%s)", settings.qdrant_url)
        return QdrantStore()

    if provider in ("azure_ai_search", "azure_search", "azure"):
        from .azure_search_store import AzureAISearchStore

        logger.info("Vector store: Azure AI Search (%s)", settings.azure_search_endpoint)
        return AzureAISearchStore()

    if provider == "local":
        if settings.azure_search_endpoint and settings.azure_search_key:
            from .azure_search_store import AzureAISearchStore

            logger.info(
                "Vector store: Azure AI Search (auto-detected from credentials; "
                "set VECTOR_STORE_PROVIDER=azure_ai_search explicitly to silence this)"
            )
            return AzureAISearchStore()

        from .local_store import LocalVectorStore

        logger.info("Vector store: in-memory (local dev mode)")
        return LocalVectorStore()

    logger.warning("Unknown VECTOR_STORE_PROVIDER '%s', defaulting to local", provider)
    from .local_store import LocalVectorStore

    return LocalVectorStore()
