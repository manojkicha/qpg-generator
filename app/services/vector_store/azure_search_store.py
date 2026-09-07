"""Azure AI Search vector store backend."""

import json
import logging
from typing import Optional

from azure.core.credentials import AzureKeyCredential
from azure.search.documents.aio import SearchClient

from app.core.config import settings

from .base import VectorRecord, VectorSearchResult, VectorStoreClient

logger = logging.getLogger(__name__)


class AzureAISearchStore(VectorStoreClient):
    """Hybrid (vector + keyword) search backed by an Azure AI Search index."""

    def __init__(self) -> None:
        self._client: Optional[SearchClient] = None

    def _get_client(self) -> SearchClient:
        if self._client is None:
            self._client = SearchClient(
                endpoint=settings.azure_search_endpoint,
                index_name=settings.azure_search_index,
                credential=AzureKeyCredential(settings.azure_search_key),
            )
        return self._client

    async def upsert_chunks(self, document_id: str, records: list[VectorRecord]) -> list[str]:
        client = self._get_client()
        indexed_ids: list[str] = []
        batch_size = 50

        for i in range(0, len(records), batch_size):
            batch = records[i : i + batch_size]
            docs = [
                {
                    "id": r.id,
                    "source_document_id": r.source_document_id,
                    "content": r.content,
                    "content_vector": r.embedding,
                    "chapter": r.chapter,
                    "topic": r.topic,
                    "heading_path": r.heading_path,
                    "page_start": r.page_start,
                    "page_end": r.page_end,
                    "image_references": json.dumps(r.image_references),
                    "created_at": r.created_at,
                }
                for r in batch
            ]
            await client.upload_documents(documents=docs)
            indexed_ids.extend(r.id for r in batch)

        logger.info("Indexed %d chunks to Azure AI Search", len(indexed_ids))
        return indexed_ids

    async def search(
        self,
        *,
        query_text: str,
        query_vector: list[float],
        document_id: str,
        top_k: int = 5,
        filter_category: Optional[str] = None,
    ) -> list[VectorSearchResult]:
        client = self._get_client()

        filter_expr = f"source_document_id eq '{document_id}'"
        if filter_category:
            filter_expr += f" and topic eq '{filter_category}'"

        results = await client.search(
            search_text=query_text,
            vector_queries=[{"kind": "vector", "vector": query_vector, "k": top_k}],
            filter=filter_expr,
            top=top_k,
        )

        search_results = []
        async for r in results:
            search_results.append(
                VectorSearchResult(
                    chunk_id=r.get("id", ""),
                    content=r.get("content", ""),
                    score=r.get("@search.score", 0.0),
                    chapter=r.get("chapter"),
                    topic=r.get("topic"),
                    page_start=r.get("page_start"),
                    page_end=r.get("page_end"),
                    heading_path=r.get("heading_path"),
                )
            )

        logger.info("Azure AI Search returned %d results", len(search_results))
        return search_results

    async def close(self) -> None:
        if self._client:
            await self._client.close()
