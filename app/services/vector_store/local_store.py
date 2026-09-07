"""In-memory vector store — used when no external vector DB is configured.

Fine for local dev (e.g. Ollama-only setups with no Docker/cloud vector DB
running), but it's per-process and non-persistent, so it's not meant for
production use. Switch `VECTOR_STORE_PROVIDER` to "qdrant" or
"azure_ai_search" for anything real.
"""

import logging
import math
from typing import Optional

from .base import VectorRecord, VectorSearchResult, VectorStoreClient

logger = logging.getLogger(__name__)


class LocalVectorStore(VectorStoreClient):
    """Cosine-similarity search over chunks held in process memory."""

    # Class-level so it's shared across instances/requests within one process,
    # the same way the previous IngestionService._local_chunks worked.
    _chunks_by_document: dict[str, list[VectorRecord]] = {}

    async def upsert_chunks(self, document_id: str, records: list[VectorRecord]) -> list[str]:
        LocalVectorStore._chunks_by_document[document_id] = records
        chunk_ids = [r.id for r in records]
        logger.info("Stored %d chunks locally for document %s", len(chunk_ids), document_id)
        return chunk_ids

    async def search(
        self,
        *,
        query_text: str,
        query_vector: list[float],
        document_id: str,
        top_k: int = 5,
        filter_category: Optional[str] = None,
    ) -> list[VectorSearchResult]:
        records = LocalVectorStore._chunks_by_document.get(document_id, [])
        if not records:
            logger.warning("No local chunks found for document %s", document_id)
            return []

        def cosine_sim(a: list[float], b: list[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b))
            norm_a = math.sqrt(sum(x * x for x in a))
            norm_b = math.sqrt(sum(x * x for x in b))
            return dot / (norm_a * norm_b + 1e-8)

        scored = []
        for record in records:
            if filter_category and record.topic and filter_category.lower() not in record.topic.lower():
                continue
            scored.append((cosine_sim(query_vector, record.embedding), record))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = [
            VectorSearchResult(
                chunk_id=record.id,
                content=record.content,
                score=score,
                chapter=record.chapter,
                topic=record.topic,
                page_start=record.page_start,
                page_end=record.page_end,
                heading_path=record.heading_path,
            )
            for score, record in scored[:top_k]
        ]

        logger.info("Local search returned %d results", len(results))
        return results
