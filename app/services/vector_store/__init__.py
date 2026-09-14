"""Vector store abstraction — swap Qdrant / Azure AI Search / Chroma / in-memory via config.

Usage:
    from app.services.vector_store import get_vector_store, VectorRecord, ChromaStore

    store = get_vector_store()
    await store.upsert_chunks(document_id, records)
    results = await store.search(query_text=..., query_vector=..., document_id=...)
"""

from .base import VectorRecord, VectorSearchResult, VectorStoreClient
from .chroma_store import ChromaStore
from .factory import get_vector_store

__all__ = [
    "VectorStoreClient",
    "VectorRecord",
    "VectorSearchResult",
    "ChromaStore",
    "get_vector_store",
]
