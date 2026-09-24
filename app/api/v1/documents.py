"""FastAPI router for document management."""

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session_factory
from app.schemas.document import DocumentCreate, DocumentResponse
from app.services.document_service import DocumentService
from app.services.ingestion_service import IngestionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

async def get_db():
    """Dependency to get a DB session."""
    async with async_session_factory() as session:
        yield session

@router.post(
    "/upload",
    response_model=DocumentResponse,
    summary="Upload and ingest a source document",
)
async def upload_document(
    file: UploadFile = File(...),
    tenant_id: str = Form(...),
    subject: Optional[str] = Form(None),
    grade: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Upload a PDF, ingest its content into the vector store, and save metadata."""
    # 1. Save file to disk
    from pathlib import Path
    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)

    import uuid
    doc_id = str(uuid.uuid4())
    file_path = data_dir / f"{doc_id}.pdf"

    content = await file.read()
    file_path.write_bytes(content)

    # 2. Create Document Record
    doc_service = DocumentService()
    doc_in = DocumentCreate(
        filename=file.filename,
        tenant_id=tenant_id,
        subject=subject,
        grade=grade
    )
    doc_record = await doc_service.create_document(db, doc_in, storage_path=str(file_path))

    # 3. Ingest Content into Vector Store
    ingestion = IngestionService()
    try:
        await ingestion.process_document(
            document_id=doc_record.id,
            document_path=str(file_path),
        )
    except Exception as e:
        logger.error("Ingestion failed for doc %s: %s", doc_record.id, e)
        # We keep the record but the content might be missing/partial
        # In production, you might want to delete the record or mark it as 'failed'
    finally:
        await ingestion.close()

    return doc_record

@router.get(
    "/subjects",
    response_model=List[dict],
    summary="List unique subjects for a tenant and grade",
)
async def list_subjects(
    tenant_id: str,
    grade: str,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a list of all unique subjects available for the given tenant and grade."""
    doc_service = DocumentService()
    return await doc_service.list_subjects(db, tenant_id, grade)

@router.get(
    "/",
    response_model=List[DocumentResponse],
    summary="List all documents for a tenant",
)
async def list_documents(
    tenant_id: str,
    subject: Optional[str] = None,
    grade: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a list of available source documents."""
    doc_service = DocumentService()
    return await doc_service.list_documents(db, tenant_id, subject, grade)

@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Get document details",
)
async def get_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get details for a specific document."""
    doc_service = DocumentService()
    doc = await doc_service.get_document(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc

@router.get(
    "/{document_id}/chunks/count",
    summary="Get the number of chunks in the vector store for a document",
)
async def get_document_chunk_count(document_id: str):
    """Retrieve the total count of embeddings/chunks stored for the given document."""
    from app.services.vector_store import get_vector_store
    store = get_vector_store()
    try:
        count = await store.count_chunks(document_id)
        return {"document_id": document_id, "chunk_count": count}
    except Exception as e:
        logger.error("Failed to count chunks for doc %s: %s", document_id, e)
        raise HTTPException(status_code=500, detail="Error retrieving chunk count from vector store")
