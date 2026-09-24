"""Book model for the catalog feature."""

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4
from typing import Optional

from sqlalchemy import Column, String, DateTime, Text, func, Index
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import Base

class BookStatus(str, Enum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"

class Book(Base):
    """Represents a book in the catalog for question paper generation."""
    __tablename__ = "books"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    grade = Column(String(50), nullable=False, index=True)
    subject = Column(String(100), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    source_document_id = Column(UUID(as_uuid=True), nullable=False, unique=True)
    file_url = Column(String(500), nullable=True)
    status = Column(String(20), default=BookStatus.PROCESSING, nullable=False, index=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index('ix_books_tenant_grade_subject_status', 'tenant_id', 'grade', 'subject', 'status'),
    )

book_table = Book.__table__
