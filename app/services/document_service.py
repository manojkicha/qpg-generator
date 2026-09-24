"""Document Service — manages metadata for uploaded source materials."""

import logging
from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.document import Document
from app.schemas.document import DocumentCreate, DocumentResponse

logger = logging.getLogger(__name__)

class DocumentService:
    """Service for managing document metadata records."""

    async def create_document(
        self, session: AsyncSession, doc_in: DocumentCreate, storage_path: Optional[str] = None
    ) -> DocumentResponse:
        """Creates a new document record in the database.
        Prevents duplicates for the same tenant, subject, and grade.
        """
        # Check for existing document with same tenant, subject, and grade
        from sqlalchemy import select
        query = select(Document).where(
            Document.tenant_id == doc_in.tenant_id,
            Document.subject == doc_in.subject,
            Document.grade == doc_in.grade
        )
        result = await session.execute(query)
        existing = result.scalars().first()

        if existing:
            # Return the existing document instead of creating a duplicate
            return DocumentResponse(
                id=str(existing.id),
                filename=existing.filename,
                tenant_id=existing.tenant_id,
                subject=existing.subject,
                grade=existing.grade,
                uploaded_at=existing.uploaded_at,
            )

        doc = Document(
            id=uuid4(),
            filename=doc_in.filename,
            tenant_id=doc_in.tenant_id,
            subject=doc_in.subject,
            grade=doc_in.grade,
            storage_path=storage_path,
            uploaded_at=datetime.now(timezone.utc),
        )
        session.add(doc)
        await session.commit()
        await session.refresh(doc)

        return DocumentResponse(
            id=str(doc.id),
            filename=doc.filename,
            tenant_id=doc.tenant_id,
            subject=doc.subject,
            grade=doc.grade,
            uploaded_at=doc.uploaded_at,
        )

    async def list_subjects(
        self, session: AsyncSession, tenant_id: str, grade: str
    ) -> List[dict]:
        """Lists all unique subjects available for a specific tenant and grade as a list of dicts."""
        from sqlalchemy import select, distinct
        query = select(distinct(Document.subject)).where(
            Document.tenant_id == tenant_id,
            Document.grade == grade
        )
        result = await session.execute(query)
        subjects = result.scalars().all()

        # Return as a list of dictionaries for better UI extensibility
        return [{"subject": s} for s in subjects if s is not None]

    async def list_documents(
        self, session: AsyncSession, tenant_id: str, subject: Optional[str] = None, grade: Optional[str] = None
    ) -> List[DocumentResponse]:
        """Lists documents for a specific tenant, optionally filtered by subject and grade."""
        query = select(Document).where(Document.tenant_id == tenant_id)
        if subject:
            query = query.where(Document.subject == subject)
        if grade:
            query = query.where(Document.grade == grade)

        result = await session.execute(query)
        docs = result.scalars().all()

        return [
            DocumentResponse(
                id=str(d.id),
                filename=d.filename,
                tenant_id=d.tenant_id,
                subject=d.subject,
                grade=d.grade,
                uploaded_at=d.uploaded_at,
            )
            for d in docs
        ]

    async def get_document(
        self, session: AsyncSession, document_id: str
    ) -> Optional[DocumentResponse]:
        """Retrieves a specific document by ID."""
        from uuid import UUID
        result = await session.get(Document, UUID(document_id))
        if not result:
            return None
        return DocumentResponse.model_validate(result)
