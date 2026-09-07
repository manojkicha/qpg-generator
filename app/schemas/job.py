"""Schemas for generation jobs."""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class JobCreate(BaseModel):
    """Schema for creating a generation job."""

    source_document_id: str
    additional_material_ids: List[str] = []
    specification: dict = Field(...)
    tenant_id: str
    # Page range for OCR/scanning (1-indexed, inclusive)
    page_start: int = Field(default=1, ge=1, description="First page to process (1-indexed)")
    page_end: Optional[int] = Field(default=None, description="Last page to process (None = all)")
    ocr_dpi: int = Field(default=200, ge=100, le=600, description="DPI for OCR rendering")


class JobResponse(BaseModel):
    """Schema for job response."""

    job_id: str
    status: str
    created_at: datetime


class JobStatusResponse(BaseModel):
    """Schema for job status response."""

    job_id: str
    status: str
    current_step: Optional[str] = None
    progress_percentage: Optional[int] = 0
    validation_summary: Optional[dict] = None
    question_paper_url: Optional[str] = None
    answer_paper_url: Optional[str] = None
    error_message: Optional[str] = None
    completed_at: Optional[datetime] = None