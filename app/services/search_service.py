"""Search Service — performs hybrid retrieval over indexed chunks.

Used by the LangGraph Retriever Agent for content-aware question generation.

The actual retrieval backend (in-memory, Azure AI Search, or Qdrant) is
selected by `VECTOR_STORE_PROVIDER` — see app/services/vector_store/. This
service doesn't know or care which one is active.
"""

import logging
from typing import Optional

from app.core.llm_client import get_embeddings_model
from app.services.vector_store import VectorSearchResult as SearchResult
from app.services.vector_store import VectorStoreClient, get_vector_store

logger = logging.getLogger(__name__)

# Re-exported for backward compatibility — callers that used to do
# `from app.services.search_service import SearchResult` keep working.
__all__ = ["SearchService", "SearchResult"]


class SearchService:
    """Hybrid search over the configured vector store of eBook chunks."""

    def __init__(self) -> None:
        self._vector_store: Optional[VectorStoreClient] = None
        self._embedder = None

    def get_vector_store(self) -> VectorStoreClient:
        if self._vector_store is None:
            self._vector_store = get_vector_store()
        return self._vector_store

    async def get_embedder(self):
        if self._embedder is None:
            self._embedder = get_embeddings_model()
        return self._embedder

    async def hybrid_search(
        self,
        query: str,
        document_id: str,
        top_k: int = 5,
        filter_category: Optional[str] = None,
    ) -> list[SearchResult]:
        """Perform hybrid search over the eBook content for one document.

        Delegates to whichever vector store is configured
        (VECTOR_STORE_PROVIDER: "local" | "azure_ai_search" | "qdrant").
        """
        logger.info("Search for query: %s (doc=%s)", query[:50], document_id)

        store = self.get_vector_store()
        embedder = await self.get_embedder()
        query_vector = await embedder.aembed_query(query)

        return await store.search(
            query_text=query,
            query_vector=query_vector,
            document_id=document_id,
            top_k=top_k,
            filter_category=filter_category,
        )

    async def close(self) -> None:
        if self._vector_store:
            await self._vector_store.close()
