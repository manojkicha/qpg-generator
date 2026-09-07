"""Vector store abstraction.

This is what lets the rest of the app (ingestion + retrieval) stay ignorant of
*which* vector database is actually storing the embeddings. Today there are
three backends (see `factory.py`):

  - LocalVectorStore    — in-memory cosine similarity, zero setup
  - AzureAISearchStore  — Azure AI Search
  - QdrantStore         — Qdrant (self-hosted via Docker, or Qdrant Cloud)

Adding a new backend means implementing `VectorStoreClient` and wiring it up
in `factory.py` — nothing in `ingestion_service.py` or `search_service.py`
needs to change.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class VectorRecord:
    """One embedded chunk, ready to be written to a vector store."""

    id: str
    content: str
    embedding: list[float]
    source_document_id: str
    chapter: Optional[str] = None
    topic: Optional[str] = None
    heading_path: Optional[str] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    image_references: list[str] = field(default_factory=list)
    created_at: Optional[str] = None


@dataclass
class VectorSearchResult:
    """A single retrieval result, provider-agnostic."""

    chunk_id: str
    content: str
    score: float
    chapter: Optional[str] = None
    topic: Optional[str] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    heading_path: Optional[str] = None


class VectorStoreClient(ABC):
    """Common interface every vector store backend implements."""

    @abstractmethod
    async def upsert_chunks(self, document_id: str, records: list[VectorRecord]) -> list[str]:
        """Write embedded chunks to the store. Returns the chunk ids written."""

    @abstractmethod
    async def search(
        self,
        *,
        query_text: str,
        query_vector: list[float],
        document_id: str,
        top_k: int = 5,
        filter_category: Optional[str] = None,
    ) -> list[VectorSearchResult]:
        """Retrieve the top_k most relevant chunks for a single document."""

    async def close(self) -> None:
        """Release any held connections. Override where there's something to close."""
        return None
