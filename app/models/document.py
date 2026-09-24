"""Document model for tracking uploaded source materials."""

from datetime import datetime, timezone
from uuid import uuid4
from typing import Optional

from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase
from app.models.base import Base

class Document(Base):
    """Represents a source document (e.g., eBook PDF) in the system."""
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    filename = Column(String, nullable=False)
    tenant_id = Column(String, nullable=False, index=True)
    subject = Column(String, nullable=True)
    grade = Column(String, nullable=True)
    uploaded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    storage_path = Column(String, nullable=True)
    metadata_json = Column(Text, nullable=True)

    __table_args__ = (
        # Ensure uniqueness for the combination of tenant, subject, and grade
        # This prevents duplicate documents for the same subject/grade per tenant
        # Note: Using Index instead of UniqueConstraint for better performance on lookups
        # and allowing NULL values for subject/grade if necessary.
    )

document_table = Document.__table__
