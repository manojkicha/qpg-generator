"""Chunk model — structural pieces of the source eBook, with metadata for retrieval."""

from typing import List, Optional
from uuid import uuid4
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase as Base_cls

class Base(Base_cls):
    pass


class ChunkMetadata:
    """Metadata attached to each content chunk."""

    def __init__(
        self,
        chunk_id: str,
        chapter: Optional[str] = None,
        topic: Optional[str] = None,
        page_start: Optional[int] = None,
        page_end: Optional[int] = None,
        image_references: Optional[list] = None,
    ):
        self.chunk_id = chunk_id
        self.chapter = chapter
        self.topic = topic
        self.page_start = page_start
        self.page_end = page_end
        self.image_references = image_references or []


class Chunk(Base):
    """A chunk of source content with structural metadata for retrieval."""

    __tablename__ = "chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    source_document_id = Column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    # Structural metadata
    chapter = Column(String(100), nullable=True)
    topic = Column(String(100), nullable=True)
    heading_path = Column(String(255), nullable=True)  # e.g., "Chapter 3 / Section 2"
    page_start = Column(Integer, nullable=True)
    page_end = Column(Integer, nullable=True)
    image_references = Column("image_references", Text, default="[]")  # JSON array

    # Content
    content = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False)  # SHA256 of chunk content
    character_count = Column(Integer, default=0)
    word_count = Column(Integer, default=0)

    # Embedding reference
    embedding_id = Column(String(128), nullable=True)  # Reference to stored embedding
    embedding_model = Column(String(100), nullable=True)

    # Indexing
    search_vector = Column(Text, nullable=True)  # Azure AI Search vector

    # Audit
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    original_order = Column(Integer, nullable=False, default=0)

    @property
    def relevance_score(self) -> float:
        """Heuristic relevance score based on completeness."""
        completeness = (
            (self.page_start is not None) + (self.page_end is not None)
        ) / 2
        return round(completeness, 2)