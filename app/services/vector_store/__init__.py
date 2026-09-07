"""Vector store abstraction — swap Qdrant / Azure AI Search / in-memory via config.

Usage:
    from app.services.vector_store import get_vector_store, VectorRecord

    store = get_vector_store()
    await store.upsert_chunks(document_id, records)
    results = await store.search(query_text=..., query_vector=..., document_id=...)
"""

from .base import VectorRecord, VectorSearchResult, VectorStoreClient
from .factory import get_vector_store

__all__ = [
    "VectorStoreClient",
    "VectorRecord",
    "VectorSearchResult",
    "get_vector_store",
]
