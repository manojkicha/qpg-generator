"""Chroma vector store backend.

A lightweight, embeddings-first vector store that runs locally or can be
deployed without a separate service (no Docker needed, unlike Qdrant).

Requires `pip install chromadb`.
"""
import logging
import asyncio
from typing import Optional

import chromadb


from app.core.config import settings
from app.services.vector_store.base import VectorRecord, VectorSearchResult, VectorStoreClient

logger = logging.getLogger(__name__)


class ChromaStore(VectorStoreClient):
    """Vector search backed by Chroma DB (embedded or client-server)."""

    def __init__(self) -> None:
        self._client: Optional[chromadb.Client] = None

    async def _get_client(self) -> chromadb.Client:
        if self._client is None:
            # Use settings to configure; if no explicit Chroma config, default to
            # an ephemeral in-process client for local dev
            self._client = chromadb.Client()
        return self._client

    async def _get_collection(self, client: chromadb.Client):
        """Get or create collection from settings."""
        collection_name = settings.chroma_collection or "question-paper-chunks"
        return await asyncio.to_thread(client.get_or_create_collection, name=collection_name)

    async def upsert_chunks(self, document_id: str, records: list[VectorRecord]) -> list[str]:
        if not records:
            return []

        client = await self._get_client()
        collection = await self._get_collection(client)

        # Chroma expects ids to be strings; our VectorRecord ids are already strings
        ids = [r.id for r in records]
        embeddings = [r.embedding for r in records]
        documents = [r.content for r in records]
        metadatas = []
        for r in records:
            meta: dict[str, Optional[str]] = {}
            if r.chapter is not None:
                meta["chapter"] = r.chapter
            if r.topic is not None:
                meta["topic"] = r.topic
            if r.heading_path is not None:
                meta["heading_path"] = r.heading_path
            if r.page_start is not None:
                meta["page_start"] = str(r.page_start)
            if r.page_end is not None:
                meta["page_end"] = str(r.page_end)
            if r.source_document_id is not None:
                meta["source_document_id"] = r.source_document_id
            if r.image_references:
                meta["image_references"] = ",".join(r.image_references)
            if r.created_at is not None:
                meta["created_at"] = r.created_at
            metadatas.append(meta)

        await asyncio.to_thread(
            collection.upsert,
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        logger.info("Indexed %d chunks to Chroma collection", len(ids))
        return ids

    async def search(
        self,
        *,
        query_text: str,
        query_vector: list[float],
        document_id: str,
        top_k: int = 5,
        filter_category: Optional[str] = None,
    ) -> list[VectorSearchResult]:
        client = await self._get_client()
        collection = await self._get_collection(client)

        where_filter: dict | None = None
        if document_id:
            where_filter = {"source_document_id": {"$eq": document_id}}

        if filter_category is not None:
            if where_filter is None:
                where_filter = {"topic": {"$eq": filter_category}}
            else:
                where_filter["topic"] = {"$eq": filter_category}

        results = await asyncio.to_thread(
            collection.query,
            query_texts=[query_text],
            query_embeddings=[query_vector],
            n_results=top_k,
            where=where_filter,
            include=["metadatas", "documents", "distances"],
        )

        search_results: list[VectorSearchResult] = []
        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for i in range(len(ids)):
            meta = metadatas[i] if i < len(metadatas) else {}
            search_results.append(
                VectorSearchResult(
                    chunk_id=ids[i] if i < len(ids) else "",
                    content=documents[i] if i < len(documents) else "",
                    score=1.0 - distances[i] if i < len(distances) else 0.0,
                    chapter=meta.get("chapter"),
                    topic=meta.get("topic"),
                    page_start=int(meta.get("page_start")) if meta.get("page_start") is not None else None,
                    page_end=int(meta.get("page_end")) if meta.get("page_end") is not None else None,
                    heading_path=meta.get("heading_path"),
                )
            )

        logger.info("Chroma search returned %d results", len(search_results))
        return search_results

    async def count_chunks(self, document_id: str) -> int:
        """Count the number of chunks for a specific document."""
        client = await self._get_client()
        collection = await self._get_collection(client)

        count = await asyncio.to_thread(
            collection.count(), # Chroma's count() doesn't support where filters in all versions,
                                # so we might need to get all and filter or use get()
        )
        # Correct way to count with filter in Chroma:
        results = await asyncio.to_thread(
            collection.get(
                where={"source_document_id": {"$eq": document_id}},
                include=[]
            )
        )
        return len(results.get("ids", []))

    async def close(self) -> None:
        if self._client is not None:
            # Chroma async client cleanup
            pass