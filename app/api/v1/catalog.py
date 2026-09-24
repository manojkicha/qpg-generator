"""API router for the Book Catalog discovery endpoints."""

from typing import List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session_factory
from app.schemas.book import BookResponse
from app.services.book_service import BookService

router = APIRouter(prefix="/catalog", tags=["catalog"])

async def get_db():
    """Dependency to get a DB session."""
    async with async_session_factory() as session:
        yield session

@router.get(
    "/grades",
    response_model=List[str],
    summary="List all grades with ready books",
)
async def list_grades(
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a list of distinct grades that have at least one READY book."""
    book_service = BookService()
    return await book_service.list_grades(db, tenant_id)

@router.get(
    "/grades/{grade}/subjects",
    response_model=List[str],
    summary="List all subjects for a specific grade",
)
async def list_subjects_for_grade(
    grade: str,
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a list of distinct subjects for a specific tenant and grade."""
    book_service = BookService()
    return await book_service.list_subjects(db, tenant_id, grade)

@router.get(
    "/grades/{grade}/subjects/{subject}/books",
    response_model=List[BookResponse],
    summary="List all books for a grade and subject",
)
async def list_books_for_subject(
    grade: str,
    subject: str,
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve all READY books for a specific tenant, grade, and subject."""
    book_service = BookService()
    return await book_service.list_books(db, tenant_id, grade, subject)
