"""Book Service — manages the book catalog and status updates."""

import logging
from uuid import uuid4
from typing import List, Optional
from sqlalchemy import select, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.book import Book, BookStatus
from app.schemas.book import BookCreate, BookResponse

logger = logging.getLogger(__name__)

class BookService:
    """Service for managing the book catalog metadata."""

    async def create_book(
        self, session: AsyncSession, tenant_id: str, grade: str, subject: str, title: str
    ) -> Book:
        """Creates a new book record in the catalog with status PROCESSING."""
        from uuid import UUID
        source_doc_id = uuid4()

        # Handle tenant_id: if it's already a UUID object, use it; otherwise, try to cast it.
        # If it's not a valid UUID, we treat it as a string for the DB (depending on DB type)
        # or let the DB handle it. For SQLite/Postgres UUID columns, we need a UUID object.
        try:
            t_id = UUID(tenant_id) if isinstance(tenant_id, str) else tenant_id
        except ValueError:
            # Fallback for non-UUID tenant IDs if the DB column allows it,
            # but based on our model it is UUID(as_uuid=True).
            # We will raise a more helpful error.
            raise ValueError(f"Invalid tenant_id format: {tenant_id}. Expected a valid UUID string.")

        book = Book(
            tenant_id=t_id,
            grade=grade,
            subject=subject,
            title=title,
            source_document_id=source_doc_id,
            status=BookStatus.PROCESSING,
        )
        session.add(book)
        await session.commit()
        await session.refresh(book)
        return book

    async def mark_ready(self, session: AsyncSession, book_id: str) -> None:
        """Marks a book as READY after successful ingestion."""
        from uuid import UUID
        book = await session.get(Book, UUID(book_id))
        if book:
            book.status = BookStatus.READY
            await session.commit()

    async def mark_failed(self, session: AsyncSession, book_id: str, error_message: str) -> None:
        """Marks a book as FAILED and logs the error."""
        from uuid import UUID
        book = await session.get(Book, UUID(book_id))
        if book:
            book.status = BookStatus.FAILED
            book.error_message = error_message
            await session.commit()

    async def list_grades(self, session: AsyncSession, tenant_id: str) -> List[str]:
        """Lists all distinct grades that have READY books for the tenant."""
        query = select(distinct(Book.grade)).where(
            Book.tenant_id == tenant_id,
            Book.status == BookStatus.READY
        )
        result = await session.execute(query)
        return sorted([r[0] for r in result.all() if r[0]])

    async def list_subjects(self, session: AsyncSession, tenant_id: str, grade: str) -> List[str]:
        """Lists all distinct subjects for a tenant and grade with READY books."""
        query = select(distinct(Book.subject)).where(
            Book.tenant_id == tenant_id,
            Book.grade == grade,
            Book.status == BookStatus.READY
        )
        result = await session.execute(query)
        return sorted([r[0] for r in result.all() if r[0]])

    async def list_books(self, session: AsyncSession, tenant_id: str, grade: str, subject: str) -> List[BookResponse]:
        """Lists all READY books for a tenant, grade, and subject."""
        query = select(Book).where(
            Book.tenant_id == tenant_id,
            Book.grade == grade,
            Book.subject == subject,
            Book.status == BookStatus.READY
        ).order_by(Book.title)

        result = await session.execute(query)
        books = result.scalars().all()
        return [BookResponse.model_validate(b) for b in books]
