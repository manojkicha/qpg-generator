"""Schemas for question paper responses."""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class QuestionPaperResponse(BaseModel):
    """Schema for question paper response."""

    id: str
    job_id: str
    tenant_id: str
    title: str
    subject: str
    academic_year: str
    duration_minutes: int
    total_marks: int
    total_questions: int
    status: str
    version: int
    pdf_url: Optional[str] = None
    answer_key_url: Optional[str] = None
    created_at: datetime
    approved_at: Optional[datetime] = None
    published_at: Optional[datetime] = None


class QuestionPaperStatusUpdate(BaseModel):
    """Schema for updating question paper status."""

    status: str = Field(..., pattern="^(draft|in_review|approved|published|archived)$")
    reviewer: Optional[str] = None
    comments: Optional[str] = None


class ChunkResponse(BaseModel):
    """Schema for chunk response."""

    id: str
    source_document_id: str
    chapter: Optional[str] = None
    topic: Optional[str] = None
    heading_path: Optional[str] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    content_preview: str
    word_count: int
    created_at: datetime