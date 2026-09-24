"""API router for Book Catalog and Uploads."""

import logging
from pathlib import Path
from typing import List
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session_factory
from app.schemas.book import BookResponse, BookUploadResponse, BulkBookIngestRequest
from app.services.book_service import BookService
from app.services.ingestion_service import IngestionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/books", tags=["books"])

async def get_db():
    """Dependency to get a DB session."""
    async with async_session_factory() as session:
        yield session

async def ingest_and_finalize_book(
    book_id: str,
    document_path: str,
    source_document_id: str,
    tenant_id: str
):
    """Background task to ingest the PDF and update book status."""
    from app.db import async_session_factory

    async with async_session_factory() as session:
        book_service = BookService()
        ingestion = IngestionService()
        try:
            # Step 1: Run the ingestion pipeline
            await ingestion.process_document(
                document_id=source_document_id,
                document_path=document_path,
            )
            # Step 2: Mark as ready
            await book_service.mark_ready(session, book_id)
            logger.info("Book %s successfully ingested and marked READY", book_id)
        except Exception as e:
            logger.error("Ingestion failed for book %s: %s", book_id, e, exc_info=True)
            await book_service.mark_failed(session, book_id, str(e))
        finally:
            await ingestion.close()

@router.post(
    "/bulk-ingest",
    response_model=List[BookUploadResponse],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Bulk ingest multiple books from URLs",
)
async def bulk_ingest_books(
    background_tasks: BackgroundTasks,
    request: BulkBookIngestRequest,
    db: AsyncSession = Depends(get_db),
):
    """Ingest multiple books from URLs in a single request."""
    book_service = BookService()
    responses = []

    for item in request.books:
        # 1. Create book record
        book = await book_service.create_book(
            db,
            request.tenant_id,
            item.grade,
            item.subject,
            item.title
        )

        # 2. Update with URL
        book.file_url = item.blob_url
        await db.commit()
        await db.refresh(book)

        # 3. Queue background task
        background_tasks.add_task(
            ingest_from_url_and_finalize_book,
            str(book.id),
            item.blob_url,
            str(book.source_document_id),
            request.tenant_id
        )

        responses.append(BookUploadResponse(
            book_id=str(book.id),
            status=book.status,
            source_document_id=str(book.source_document_id)
        ))

    return responses

@router.post(
    "/upload",
    response_model=BookUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a book to the catalog",
)
async def upload_book(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    grade: str = Form(...),
    subject: str = Form(...),
    title: str = Form(...),
    tenant_id: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a book PDF, create a catalog entry, and start background ingestion."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty PDF file")

    book_service = BookService()
    # 1. Create book record (Status: PROCESSING)
    book = await book_service.create_book(db, tenant_id, grade, subject, title)

    # 2. Persist file to disk
    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)
    document_path = data_dir / f"{book.source_document_id}.pdf"
    document_path.write_bytes(content)

    # 3. Queue background ingestion
    background_tasks.add_task(
        ingest_and_finalize_book,
        str(book.id),
        str(document_path),
        str(book.source_document_id),
        tenant_id
    )

    return BookUploadResponse(
        book_id=str(book.id),
        status=book.status,
        source_document_id=str(book.source_document_id)
    )

@router.post(
    "/ingest-from-url",
    response_model=BookUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest a book from a URL to the catalog",
)
async def ingest_book_from_url(
    background_tasks: BackgroundTasks,
    blob_url: str = Form(...),
    grade: str = Form(...),
    subject: str = Form(...),
    title: str = Form(...),
    tenant_id: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Ingest a book from a URL, create a catalog entry, and start background processing."""
    book_service = BookService()

    # 1. Create book record (Status: PROCESSING)
    book = await book_service.create_book(db, tenant_id, grade, subject, title)

    # 2. Save the URL to the book record
    book.file_url = blob_url
    await db.commit()
    await db.refresh(book)

    # 3. Queue background task for downloading and ingestion
    background_tasks.add_task(
        ingest_from_url_and_finalize_book,
        str(book.id),
        blob_url,
        str(book.source_document_id),
        tenant_id
    )

    return BookUploadResponse(
        book_id=str(book.id),
        status=book.status,
        source_document_id=str(book.source_document_id)
    )

async def ingest_from_url_and_finalize_book(
    book_id: str,
    blob_url: str,
    source_document_id: str,
    tenant_id: str
):
    """Background task to download PDF from URL and then ingest."""
    import httpx
    from pathlib import Path
    from app.db import async_session_factory

    async with async_session_factory() as session:
        book_service = BookService()
        ingestion = IngestionService()
        try:
            # 1. Download the file
            data_dir = Path("data")
            data_dir.mkdir(parents=True, exist_ok=True)
            document_path = data_dir / f"{source_document_id}.pdf"

            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.get(blob_url)
                response.raise_for_status()
                document_path.write_bytes(response.content)

            # 2. Run the ingestion pipeline
            await ingestion.process_document(
                document_id=source_document_id,
                document_path=str(document_path),
            )
            # 3. Mark as ready
            await book_service.mark_ready(session, book_id)
            logger.info("Book %s ingested from URL and marked READY", book_id)
        except Exception as e:
            logger.error("URL ingestion failed for book %s: %s", book_id, e, exc_info=True)
            await book_service.mark_failed(session, book_id, str(e))
        finally:
            await ingestion.close()


