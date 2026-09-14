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
        """Creates a new document record in the database."""
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
        return DocumentResponse.model_validate(doc)

    async def list_documents(
        self, session: AsyncSession, tenant_id: str, subject: Optional[str] = None
    ) -> List[DocumentResponse]:
        """Lists documents for a specific tenant, optionally filtered by subject."""
        query = select(Document).where(Document.tenant_id == tenant_id)
        if subject:
            query = query.where(Document.subject == subject)

        result = await session.execute(query)
        docs = result.scalars().all()
        return [DocumentResponse.model_validate(d) for d in docs]

    async def get_document(
        self, session: AsyncSession, document_id: str
    ) -> Optional[DocumentResponse]:
        """Retrieves a specific document by ID."""
        from uuid import UUID
        result = await session.get(Document, UUID(document_id))
        if not result:
            return None
        return DocumentResponse.model_validate(result)
