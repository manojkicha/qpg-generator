"""Qdrant vector store backend.

Points at a self-hosted Qdrant instance (e.g. the standard Docker image,
dashboard at http://localhost:6333/dashboard) or Qdrant Cloud — set
QDRANT_URL / QDRANT_API_KEY accordingly. The collection is created
automatically on first write, sized to match whatever embedding model
(Ollama, OpenAI, or Azure OpenAI) is configured.

Requires the `qdrant-client` package: pip install qdrant-client
"""

import json
import logging
import uuid
from typing import Optional

from qdrant_client import AsyncQdrantClient, models

from app.core.config import settings

from .base import VectorRecord, VectorSearchResult, VectorStoreClient

logger = logging.getLogger(__name__)

# Qdrant point IDs must be an unsigned int or a UUID. Our chunk ids are our
# own strings (e.g. "docid_chunk_3"), so we derive a stable UUID from them
# here and keep the original string in the payload for round-tripping.
_ID_NAMESPACE = uuid.UUID("a9f36c9e-6b34-4c8b-9c34-2f1a6a7b9c11")


def _point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(_ID_NAMESPACE, chunk_id))


class QdrantStore(VectorStoreClient):
    """Vector search backed by a Qdrant collection."""

    def __init__(self) -> None:
        self._client: Optional[AsyncQdrantClient] = None
        self._ensured_collections: set[str] = set()

    def _get_client(self) -> AsyncQdrantClient:
        if self._client is None:
            self._client = AsyncQdrantClient(
                url=settings.qdrant_url,
                api_key=settings.qdrant_api_key or None,
            )
        return self._client

    async def _ensure_collection(self, client: AsyncQdrantClient, vector_size: int) -> None:
        collection = settings.qdrant_collection
        if collection in self._ensured_collections:
            return

        if not await client.collection_exists(collection):
            await client.create_collection(
                collection_name=collection,
                vectors_config=models.VectorParams(
                    size=vector_size, distance=models.Distance.COSINE
                ),
            )
            logger.info("Created Qdrant collection '%s' (size=%d)", collection, vector_size)

        self._ensured_collections.add(collection)

    async def upsert_chunks(self, document_id: str, records: list[VectorRecord]) -> list[str]:
        if not records:
            return []

        client = self._get_client()
        await self._ensure_collection(client, vector_size=len(records[0].embedding))

        points = [
            models.PointStruct(
                id=_point_id(r.id),
                vector=r.embedding,
                payload={
                    "chunk_id": r.id,
                    "source_document_id": r.source_document_id,
                    "content": r.content,
                    "chapter": r.chapter,
                    "topic": r.topic,
                    "heading_path": r.heading_path,
                    "page_start": r.page_start,
                    "page_end": r.page_end,
                    "image_references": json.dumps(r.image_references),
                    "created_at": r.created_at,
                },
            )
            for r in records
        ]

        await client.upsert(collection_name=settings.qdrant_collection, points=points)
        logger.info(
            "Indexed %d chunks to Qdrant collection '%s'", len(points), settings.qdrant_collection
        )
        return [r.id for r in records]

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

        if not await client.collection_exists(settings.qdrant_collection):
            logger.warning("Qdrant collection '%s' does not exist yet", settings.qdrant_collection)
            return []

        must_conditions = [
            models.FieldCondition(
                key="source_document_id", match=models.MatchValue(value=document_id)
            )
        ]
        if filter_category:
            must_conditions.append(
                models.FieldCondition(key="topic", match=models.MatchValue(value=filter_category))
            )

        hits = await client.search(
            collection_name=settings.qdrant_collection,
            query_vector=query_vector,
            query_filter=models.Filter(must=must_conditions),
            limit=top_k,
            with_payload=True,
        )

        search_results = []
        for point in hits:
            payload = point.payload or {}
            search_results.append(
                VectorSearchResult(
                    chunk_id=payload.get("chunk_id", str(point.id)),
                    content=payload.get("content", ""),
                    score=point.score,
                    chapter=payload.get("chapter"),
                    topic=payload.get("topic"),
                    page_start=payload.get("page_start"),
                    page_end=payload.get("page_end"),
                    heading_path=payload.get("heading_path"),
                )
            )

        logger.info("Qdrant search returned %d results", len(search_results))
        return search_results

    async def close(self) -> None:
        if self._client:
            await self._client.close()
