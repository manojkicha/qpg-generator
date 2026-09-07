"""Question Paper model — the core entity representing a generated question paper."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

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


class QuestionPaperStatus(str, Enum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class QuestionPaper(Base):
    """A generated question paper with its metadata and structure."""

    __tablename__ = "question_papers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("generation_jobs.id"), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    # Paper metadata
    title = Column(String(255), nullable=False)
    subject = Column(String(100), nullable=False)
    academic_year = Column(String(20), nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    total_marks = Column(Integer, nullable=False)
    total_questions = Column(Integer, nullable=False)
    version = Column(Integer, default=1)

    # Status
    status = Column(SQLEnum(QuestionPaperStatus), default=QuestionPaperStatus.DRAFT, nullable=False)

    # Content
    paper_json = Column(Text, nullable=False)  # Full question paper as JSON
    spec_hash = Column(String(64), nullable=False)  # Hash of specification used

    # URLs
    pdf_url = Column(String(500), nullable=True)
    answer_key_url = Column(String(500), nullable=True)

    # Audit
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    approved_by = Column(String(255), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<QuestionPaper(id={self.id}, title={self.title}, status={self.status})>"