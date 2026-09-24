"""Schema definitions for the Book Catalog."""

from datetime import datetime
from enum import Enum
from uuid import UUID
from typing import Optional, List
from pydantic import BaseModel, Field

class BookStatus(str, Enum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"

class BookBase(BaseModel):
    """Base book schema."""
    tenant_id: str
    grade: str
    subject: str
    title: str
    source_document_id: str

class BookCreate(BookBase):
    """Schema for internal book creation."""
    pass

class BulkBookItem(BaseModel):
    """Item for bulk ingestion request."""
    blob_url: str
    title: str
    subject: str
    grade: str

class BulkBookIngestRequest(BaseModel):
    """Schema for bulk ingestion of books."""
    tenant_id: str
    books: List[BulkBookItem]

class BookResponse(BookBase):
    """Schema for returning a book record."""
    id: str
    status: BookStatus
    created_at: datetime

    class Config:
        from_attributes = True

class BookUploadResponse(BaseModel):
    """Schema for the initial upload response."""
    book_id: str
    status: BookStatus
    source_document_id: str
