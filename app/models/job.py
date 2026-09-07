"""Job model — tracks generation jobs through their lifecycle."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
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


class JobStatus(str, Enum):
    QUEUED = "queued"
    INGESTING = "ingesting"
    INDEXING = "indexing"
    GENERATING = "generating"
    VALIDATING = "validating"
    COMPILING = "compiling"
    REVIEW_PENDING = "review_pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GenerationJob(Base):
    """Tracks a question paper generation job end-to-end."""

    __tablename__ = "generation_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id = Column(String(64), unique=True, nullable=False, index=True)
    source_document_id = Column(UUID(as_uuid=True), nullable=False)
    additional_material_ids = Column("additional_material_ids", Text, default="[]")  # JSON array of UUIDs
    specification = Column(Text, nullable=False)  # JSON spec
    status = Column(SQLEnum(JobStatus), default=JobStatus.QUEUED, nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    # Progress tracking
    current_step = Column(String(64), default="queued")
    progress_percentage = Column(Integer, default=0)
    validation_summary = Column(Text, nullable=True)  # JSON

    # Results
    question_paper_url = Column(String(500), nullable=True)
    answer_paper_url = Column(String(500), nullable=True)
    question_paper_json_url = Column(String(500), nullable=True)

    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)

    # Human review
    reviewed_by = Column(String(255), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    review_comments = Column(Text, nullable=True)

    @property
    def is_terminal(self) -> bool:
        return self.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)


# Alias for backward compatibility
Job = GenerationJob