"""Schema definitions for document management."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

class DocumentBase(BaseModel):
    """Base schema for a document."""
    filename: str = Field(..., description="Original name of the uploaded file")
    tenant_id: str = Field(..., description="Tenant/organization identifier")
    subject: Optional[str] = Field(None, description="Subject area (e.g., EVS, Maths)")
    grade: Optional[str] = Field(None, description="Grade level (e.g., Grade 1)")

class DocumentCreate(DocumentBase):
    """Schema for creating a document record."""
    pass

class DocumentResponse(DocumentBase):
    """Schema for returning a document record."""
    id: str
    uploaded_at: datetime

    class Config:
        from_attributes = True
