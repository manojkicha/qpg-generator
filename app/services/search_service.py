"""Search Service — performs hybrid retrieval over indexed chunks.

Used by the LangGraph Retriever Agent for content-aware question generation.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from azure.core.credentials import AzureKeyCredential
from azure.search.documents.aio import SearchClient

from app.core.config import settings
from app.core.llm_client import get_embeddings_model

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single retrieval result from the search index."""

    chunk_id: str
    content: str
    score: float
    chapter: Optional[str] = None
    topic: Optional[str] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    heading_path: Optional[str] = None


class SearchService:
    """Hybrid search over Azure AI Search index of eBook chunks."""

    def __init__(self) -> None:
        self._search_client: Optional[SearchClient] = None
        self._embedder = None

    async def get_search_client(self) -> SearchClient:
        if self._search_client is None:
            self._search_client = SearchClient(
                endpoint=settings.azure_search_endpoint,
                index_name=settings.azure_search_index,
                credential=AzureKeyCredential(settings.azure_search_key),
            )
        return self._search_client

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
        """Perform hybrid search on the eBook content.

        Uses Azure AI Search if configured, otherwise falls back to
        in-memory cosine similarity search over locally stored chunks.
        """
        logger.info("Search for query: %s (doc=%s)", query[:50], document_id)

        if settings.azure_search_endpoint and settings.azure_search_key:
            return await self._search_azure(query, document_id, top_k, filter_category)
        else:
            return await self._search_local(query, document_id, top_k, filter_category)

    async def _search_local(
        self,
        query: str,
        document_id: str,
        top_k: int,
        filter_category: Optional[str],
    ) -> list[SearchResult]:
        """Simple local search using cosine similarity on stored embeddings."""
        import math

        # Access locally stored chunks
        from app.services.ingestion_service import IngestionService
        chunks = IngestionService._local_chunks.get(document_id, [])
        if not chunks:
            logger.warning("No local chunks found for document %s", document_id)
            return []

        embedder = await self.get_embedder()
        query_vec = await embedder.aembed_query(query)

        def cosine_sim(a: list, b: list) -> float:
            dot = sum(x * y for x, y in zip(a, b))
            norm_a = math.sqrt(sum(x * x for x in a))
            norm_b = math.sqrt(sum(x * x for x in b))
            return dot / (norm_a * norm_b + 1e-8)

        scored = []
        for chunk in chunks:
            if filter_category:
                meta = chunk.get("metadata")
                topic = meta.topic if meta else None
                if topic and filter_category.lower() not in topic.lower():
                    continue

            score = cosine_sim(query_vec, chunk["embedding"])
            scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, chunk in scored[:top_k]:
            meta = chunk["metadata"]
            results.append(SearchResult(
                chunk_id=f"{document_id}_chunk_{len(results)}",
                content=chunk["content"],
                score=score,
                chapter=meta.chapter if meta else None,
                topic=meta.topic if meta else None,
                page_start=meta.page_range[0] if meta and meta.page_range else None,
                page_end=meta.page_range[1] if meta and meta.page_range else None,
                heading_path=meta.heading_path if meta else None,
            ))

        logger.info("Local search returned %d results", len(results))
        return results

    async def _search_azure(
        self,
        query: str,
        document_id: str,
        top_k: int,
        filter_category: Optional[str],
    ) -> list[SearchResult]:
        """Search using Azure AI Search."""
        client = await self.get_search_client()
        embedder = await self.get_embedder()
        query_vector = await embedder.aembed_query(query)

        filter_expr = f"source_document_id eq '{document_id}'"
        if filter_category:
            filter_expr += f" and topic eq '{filter_category}'"

        results = await client.search(
            search_text=query,
            vector_queries=[{"kind": "vector", "vector": query_vector, "k": top_k}],
            filter=filter_expr,
            top=top_k,
        )

        search_results = []
        async for r in results:
            search_results.append(SearchResult(
                chunk_id=r.get("id", ""),
                content=r.get("content", ""),
                score=r.get("@search.score", 0.0),
                chapter=r.get("chapter"),
                topic=r.get("topic"),
                page_start=r.get("page_start"),
                page_end=r.get("page_end"),
                heading_path=r.get("heading_path"),
            ))

        logger.info("Azure search returned %d results", len(search_results))
        return search_results

    async def close(self) -> None:
        if self._search_client:
            await self._search_client.close()