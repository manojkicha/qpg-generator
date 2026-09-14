"""Response schema for the PDF upload POC endpoint."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class PDFGenerationResponse(BaseModel):
    """Result returned by the PDF-to-question-paper POC endpoint."""

    job_id: str
    status: str
    source_document_id: str
    question_paper: Optional[dict[str, Any]] = None
    answer_key: Optional[dict[str, Any]] = None
    validation_summary: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None
    completed_at: Optional[datetime] = None
