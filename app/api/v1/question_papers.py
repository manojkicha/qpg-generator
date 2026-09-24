"""FastAPI router for question paper generation endpoints.

Based on SDD Section 12.1 API Contract:
- POST /api/v1/question-papers/generate — start generation job
- GET /api/v1/question-papers/jobs/{jobId} — get job status
- POST /api/v1/question-papers/generate-from-pdf — POC: upload PDF and generate
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse

from app.schemas import JobCreate, JobResponse, JobStatusResponse, PDFGenerationResponse
from app.schemas.specification import QuestionPaperValidationSummary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/question-papers", tags=["question-papers"])


# In-memory job store (replace with Redis/DB in production)
_jobs: dict[str, dict] = {}


@router.post(
    "/generate",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start question paper generation",
)
async def generate_question_paper(
    request: JobCreate,
    background_tasks: BackgroundTasks,
) -> JobResponse:
    """Start a question paper generation job.

    The job runs asynchronously. Poll GET /api/v1/question-papers/jobs/{jobId}
    for status updates.
    """
    job_id = str(uuid4())

    job_record = {
        "job_id": job_id,
        "status": "queued",
        "current_step": "queued",
        "progress_percentage": 0,
        "specification": request.specification,
        "source_document_id": request.source_document_id,
        "additional_material_ids": request.additional_material_ids,
        "tenant_id": request.tenant_id,
        "page_start": request.page_start,
        "page_end": request.page_end,
        "ocr_dpi": request.ocr_dpi,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "validation_summary": None,
        "question_paper_url": None,
        "answer_paper_url": None,
        "error_message": None,
        "completed_at": None,
    }

    _jobs[job_id] = job_record

    # Queue the background task
    background_tasks.add_task(run_generation_pipeline, job_id, job_record)

    logger.info("Created generation job: %s", job_id)

    return JobResponse(
        job_id=job_id,
        status="queued",
        created_at=datetime.now(timezone.utc),
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Get job status",
)
async def get_job_status(job_id: str) -> JobStatusResponse:
    """Get the current status of a generation job."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    validation_summary = None
    if job.get("validation_summary"):
        try:
            validation_summary = json.loads(job["validation_summary"])
        except Exception:
            validation_summary = job["validation_summary"]

    return JobStatusResponse(
        job_id=job_id,
        status=job["status"],
        current_step=job.get("current_step"),
        progress_percentage=job.get("progress_percentage", 0),
        validation_summary=validation_summary,
        question_paper_url=job.get("question_paper_url"),
        answer_paper_url=job.get("answer_paper_url"),
        error_message=job.get("error_message"),
        completed_at=datetime.fromisoformat(job["completed_at"])
        if job.get("completed_at")
        else None,
    )


@router.post(
    "/generate-from-pdf",
    response_model=PDFGenerationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate question paper from PDF upload (POC)",
)
async def generate_question_paper_from_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="PDF file to extract content from"),
    specification: str = Form(..., description="JSON specification for question paper generation"),
    tenant_id: str = Form(..., description="Tenant/organization identifier"),
) -> PDFGenerationResponse:
    """POC endpoint: upload a PDF and start question paper generation.

    Accepts a PDF file and a JSON specification. The PDF content is extracted
    (text/chunks) and the generation pipeline runs asynchronously.

    Returns a job_id that can be polled via GET /api/v1/question-papers/jobs/{jobId}.
    """
    # Validate the specification JSON
    try:
        spec_dict = json.loads(specification)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid specification JSON: {e}",
        )

    # Read PDF content as bytes
    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty PDF file",
        )

    job_id = str(uuid4())
    document_id = str(uuid4())

    job_record = {
        "job_id": job_id,
        "status": "ingesting",
        "current_step": "ingesting",
        "progress_percentage": 10,
        "specification": spec_dict,
        "source_document_id": document_id,
        "additional_material_ids": [],
        "tenant_id": tenant_id,
        "page_start": 1,
        "page_end": None,
        "ocr_dpi": 200,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "validation_summary": None,
        "question_paper_url": None,
        "answer_paper_url": None,
        "error_message": None,
        "completed_at": None,
        "pdf_bytes": pdf_bytes,  # temporarily store for the background task
    }

    _jobs[job_id] = job_record

    # Queue the background task with the PDF bytes included
    background_tasks.add_task(run_generation_pipeline_from_pdf, job_id, job_record)

    logger.info("Created PDF generation job: %s", job_id)

    return PDFGenerationResponse(
        job_id=job_id,
        status="ingesting",
        source_document_id=document_id,
    )


async def run_generation_pipeline_from_pdf(job_id: str, job_record: dict) -> None:
    """Run the existing generation pipeline from an uploaded PDF."""
    from pathlib import Path

    from app.services import IngestionService, GenerationService
    from app.services.compilation_service import CompilationService
    from app.services.pdf_rendering_service import PDFRenderingService

    # Persist the uploaded PDF so the ingestion pipeline can read it by path
    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)
    document_path = data_dir / f"{job_record['source_document_id']}.pdf"
    document_path.write_bytes(job_record.pop("pdf_bytes", b""))

    # Reuse the existing pipeline logic, but point it at the uploaded file
    try:
        # Step 1: Ingestion
        job_record["status"] = "ingesting"
        job_record["current_step"] = "ingestion"
        job_record["progress_percentage"] = 10

        from uuid import UUID
        standard_doc_id = str(UUID(job_record["source_document_id"]))
        document_path = data_dir / f"{standard_doc_id}.pdf"
        document_path.write_bytes(job_record.pop("pdf_bytes", b""))

        ingestion = IngestionService()
        try:
            chunk_ids = await ingestion.process_document(
                document_id=standard_doc_id,
                document_path=str(document_path),
                page_start=job_record.get("page_start", 1),
                page_end=job_record.get("page_end"),
                ocr_dpi=job_record.get("ocr_dpi", 200),
            )
        finally:
            await ingestion.close()

        # Step 2: Generation
        job_record["status"] = "generating"
        job_record["current_step"] = "generation"
        job_record["progress_percentage"] = 40

        from app.services import SearchService

        search = SearchService()
        generation = GenerationService()
        try:
            spec = job_record["specification"]
            query = f"{spec.get('subject', '')} {spec.get('title', '')}"
            search_results = await search.hybrid_search(
                query=query,
                document_id=job_record["source_document_id"],
                top_k=5,
            )

            from app.services.ingestion_service import ChunkMetadata

            context_chunks = []
            for r in search_results:
                meta = ChunkMetadata(
                    chapter=r.chapter,
                    topic=r.topic,
                    page_range=(r.page_start, r.page_end) if r.page_start else None,
                    heading_path=r.heading_path,
                )
                context_chunks.append((r.content, meta))

            result = await generation.generate_questions(
                job_id=job_record["job_id"],
                specification=spec,
                context_chunks=context_chunks,
            )
        finally:
            await search.close()
            await generation.close()

        # Step 3: Compilation
        job_record["status"] = "validating"
        job_record["current_step"] = "validation"
        job_record["progress_percentage"] = 70

        compiler = CompilationService()
        compiled = compiler.compile(
            questions=result.questions,
            specification=job_record["specification"],
            job_id=job_id,
            tenant_id=job_record["tenant_id"],
        )

        # Step 4: Render PDFs & Markdown
        job_record["status"] = "review_pending"
        job_record["current_step"] = "review"
        job_record["progress_percentage"] = 90

        from app.services.markdown_rendering_service import MarkdownRenderingService
        md_renderer = MarkdownRenderingService()
        renderer = PDFRenderingService()

        try:
            # 1. Generate Markdown (Primary)
            question_paper_md = md_renderer.render_question_paper(compiled.question_paper)
            answer_key_md = md_renderer.render_answer_key(compiled.answer_key)

            question_paper_md_path = data_dir / f"{job_id}_question_paper.md"
            answer_key_md_path = data_dir / f"{job_id}_answer_key.md"
            question_paper_md_path.write_text(question_paper_md, encoding="utf-8")
            answer_key_md_path.write_text(answer_key_md, encoding="utf-8")

            job_record["question_paper_md_url"] = str(question_paper_md_path)
            job_record["answer_paper_md_url"] = str(answer_key_md_path)

            # 2. Generate JSON (Structured Data)
            question_paper_json_path = data_dir / f"{job_id}_question_paper.json"
            answer_key_json_path = data_dir / f"{job_id}_answer_key.json"
            question_paper_json_path.write_text(json.dumps(compiled.question_paper, indent=2), encoding="utf-8")
            answer_key_json_path.write_text(json.dumps(compiled.answer_key, indent=2), encoding="utf-8")

            job_record["question_paper_json_url"] = str(question_paper_json_path)
            job_record["answer_key_json_url"] = str(answer_key_json_path)

            # 3. Generate PDF (Optional/Fallback)
            question_paper_pdf = await renderer.render_question_paper(compiled.question_paper)
            answer_key_pdf = await renderer.render_answer_key(compiled.answer_key)

            question_paper_path = data_dir / f"{job_id}_question_paper.pdf"
            answer_key_path = data_dir / f"{job_id}_answer_key.pdf"
            question_paper_path.write_bytes(question_paper_pdf)
            answer_key_path.write_bytes(answer_key_pdf)

            job_record["question_paper_url"] = str(question_paper_path)
            job_record["answer_paper_url"] = str(answer_key_path)
        except Exception as render_error:
            logger.warning("Rendering failed for job %s: %s", job_id, render_error)

        job_record["question_paper"] = compiled.question_paper
        job_record["answer_key"] = compiled.answer_key
        job_record["validation_summary"] = json.dumps(result.validation_summary)
        job_record["completed_at"] = datetime.now(timezone.utc).isoformat()
        job_record["status"] = "completed"
        job_record["current_step"] = "completed"
        job_record["progress_percentage"] = 100

        logger.info("PDF generation job %s completed", job_id)

    except Exception as e:
        logger.error("PDF generation job %s failed: %s", job_id, str(e), exc_info=True)
        job_record["status"] = "failed"
        job_record["current_step"] = "failed"
        job_record["error_message"] = str(e)
        job_record["completed_at"] = datetime.now(timezone.utc).isoformat()


@router.post(
    "/generate-from-blob-url",
    response_model=PDFGenerationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate question paper from Azure Blob Storage URL (POC)",
)
async def generate_question_paper_from_blob_url(
    background_tasks: BackgroundTasks,
    blob_url: str = Form(..., description="Azure Blob Storage URL of the input PDF document"),
    specification: str = Form(..., description="JSON specification for question paper generation"),
    tenant_id: str = Form(..., description="Tenant/organization identifier"),
) -> PDFGenerationResponse:
    """POC endpoint: accept an Azure Blob Storage URL and start question paper generation.

    The PDF at the given blob URL is downloaded, then ingested via Azure Document
    Intelligence (or the configured extraction backend), embedded into Chroma DB,
    and the question paper / answer key PDFs are generated asynchronously.

    Returns a job_id that can be polled via GET /api/v1/question-papers/jobs/{jobId}.
    """
    # Validate the specification JSON
    try:
        spec_dict = json.loads(specification)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid specification JSON: {e}",
        )

    if not blob_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="blob_url is required",
        )

    job_id = str(uuid4())
    document_id = str(uuid4())

    job_record = {
        "job_id": job_id,
        "status": "ingesting",
        "current_step": "ingesting",
        "progress_percentage": 10,
        "specification": spec_dict,
        "source_document_id": document_id,
        "additional_material_ids": [],
        "tenant_id": tenant_id,
        "page_start": 1,
        "page_end": None,
        "ocr_dpi": 200,
        "blob_url": blob_url,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "validation_summary": None,
        "question_paper_url": None,
        "answer_paper_url": None,
        "error_message": None,
        "completed_at": None,
    }

    _jobs[job_id] = job_record

    # Queue the background task with the blob URL included
    background_tasks.add_task(run_generation_pipeline_from_blob, job_id, job_record)

    logger.info("Created blob-URL generation job: %s (blob_url=%s)", job_id, blob_url)

    return PDFGenerationResponse(
        job_id=job_id,
        status="ingesting",
        source_document_id=document_id,
    )


async def run_generation_pipeline_from_blob(job_id: str, job_record: dict) -> None:
    """Background task that runs the full generation pipeline from an Azure Blob URL."""
    import httpx
    from pathlib import Path

    from app.services import IngestionService, GenerationService
    from app.services.compilation_service import CompilationService
    from app.services.pdf_rendering_service import PDFRenderingService

    blob_url = job_record.pop("blob_url", None)
    document_id = job_record["source_document_id"]
    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)

    # Download the PDF from the blob URL
    document_path = data_dir / "test.pdf"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            logger.info("Downloading PDF from blob URL: %s", blob_url)
            response = await client.get(blob_url)
            response.raise_for_status()
            document_path.write_bytes(response.content)
        logger.info("PDF downloaded to %s (%d bytes)", document_path, len(response.content))
    except Exception as download_error:
        logger.error("Failed to download PDF from blob URL: %s", download_error, exc_info=True)
        job_record["status"] = "failed"
        job_record["current_step"] = "failed"
        job_record["error_message"] = f"Failed to download PDF from blob URL: {download_error}"
        job_record["completed_at"] = datetime.now(timezone.utc).isoformat()
        return

    # Reuse the same pipeline logic as generate-from-pdf
    try:
        # Step 1: Ingestion
        job_record["status"] = "ingesting"
        job_record["current_step"] = "ingestion"
        job_record["progress_percentage"] = 10

        ingestion = IngestionService()
        try:
            chunk_ids = await ingestion.process_document(
                document_id=document_id,
                document_path=str(document_path),
                page_start=job_record.get("page_start", 1),
                page_end=job_record.get("page_end"),
                ocr_dpi=job_record.get("ocr_dpi", 200),
            )
        finally:
            await ingestion.close()

        # Step 2: Generation
        job_record["status"] = "generating"
        job_record["current_step"] = "generation"
        job_record["progress_percentage"] = 40

        from app.services import SearchService

        search = SearchService()
        generation = GenerationService()
        try:
            spec = job_record["specification"]
            query = f"{spec.get('subject', '')} {spec.get('title', '')}"
            search_results = await search.hybrid_search(
                query=query,
                document_id=job_record["source_document_id"],
                top_k=5,
            )

            from app.services.ingestion_service import ChunkMetadata

            context_chunks = []
            for r in search_results:
                meta = ChunkMetadata(
                    chapter=r.chapter,
                    topic=r.topic,
                    page_range=(r.page_start, r.page_end) if r.page_start else None,
                    heading_path=r.heading_path,
                )
                context_chunks.append((r.content, meta))

            result = await generation.generate_questions(
                job_id=job_record["job_id"],
                specification=spec,
                context_chunks=context_chunks,
            )
        finally:
            await search.close()
            await generation.close()

        # Step 3: Compilation
        job_record["status"] = "validating"
        job_record["current_step"] = "validation"
        job_record["progress_percentage"] = 70

        compiler = CompilationService()
        compiled = compiler.compile(
            questions=result.questions,
            specification=job_record["specification"],
            job_id=job_id,
            tenant_id=job_record["tenant_id"],
        )

        # Step 4: Render PDFs & Markdown
        job_record["status"] = "review_pending"
        job_record["current_step"] = "review"
        job_record["progress_percentage"] = 90

        from app.services.markdown_rendering_service import MarkdownRenderingService
        md_renderer = MarkdownRenderingService()
        renderer = PDFRenderingService()

        try:
            # 1. Generate Markdown (Primary)
            question_paper_md = md_renderer.render_question_paper(compiled.question_paper)
            answer_key_md = md_renderer.render_answer_key(compiled.answer_key)

            question_paper_md_path = data_dir / f"{job_id}_question_paper.md"
            answer_key_md_path = data_dir / f"{job_id}_answer_key.md"
            question_paper_md_path.write_text(question_paper_md, encoding="utf-8")
            answer_key_md_path.write_text(answer_key_md, encoding="utf-8")

            job_record["question_paper_md_url"] = str(question_paper_md_path)
            job_record["answer_paper_md_url"] = str(answer_key_md_path)

            # 2. Generate JSON (Structured Data)
            question_paper_json_path = data_dir / f"{job_id}_question_paper.json"
            answer_key_json_path = data_dir / f"{job_id}_answer_key.json"
            question_paper_json_path.write_text(json.dumps(compiled.question_paper, indent=2), encoding="utf-8")
            answer_key_json_path.write_text(json.dumps(compiled.answer_key, indent=2), encoding="utf-8")

            job_record["question_paper_json_url"] = str(question_paper_json_path)
            job_record["answer_key_json_url"] = str(answer_key_json_path)

            # 3. Generate PDF (Optional/Fallback)
            question_paper_pdf = await renderer.render_question_paper(compiled.question_paper)
            answer_key_pdf = await renderer.render_answer_key(compiled.answer_key)

            question_paper_path = data_dir / f"{job_id}_question_paper.pdf"
            answer_key_path = data_dir / f"{job_id}_answer_key.pdf"
            question_paper_path.write_bytes(question_paper_pdf)
            answer_key_path.write_bytes(answer_key_pdf)

            job_record["question_paper_url"] = str(question_paper_path)
            job_record["answer_paper_url"] = str(answer_key_path)
        except Exception as render_error:
            logger.warning("Rendering failed for job %s: %s", job_id, render_error)

        job_record["question_paper"] = compiled.question_paper
        job_record["answer_key"] = compiled.answer_key
        job_record["validation_summary"] = json.dumps(result.validation_summary)
        job_record["completed_at"] = datetime.now(timezone.utc).isoformat()
        job_record["status"] = "completed"
        job_record["current_step"] = "completed"
        job_record["progress_percentage"] = 100

        logger.info("Blob-URL generation job %s completed", job_id)

    except Exception as e:
        logger.error("Blob-URL generation job %s failed: %s", job_id, str(e), exc_info=True)
        job_record["status"] = "failed"
        job_record["current_step"] = "failed"
        job_record["error_message"] = str(e)
        job_record["completed_at"] = datetime.now(timezone.utc).isoformat()


@router.post(
    "/jobs/{job_id}/approve",
    status_code=status.HTTP_200_OK,
    summary="Approve generated question paper",
)
async def approve_question_paper(
    job_id: str,
    reviewer: str = "admin",
    comments: Optional[str] = None,
) -> dict:
    """Human review approval endpoint.

    After generation, an admin can approve or request changes.
    """
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    if job["status"] not in ("review_pending", "completed"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job is not pending review (status: {job['status']})",
        )

    job["status"] = "completed"
    job["reviewed_by"] = reviewer
    job["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    job["review_comments"] = comments

    logger.info("Job %s approved by %s", job_id, reviewer)

    return {"message": "Question paper approved", "job_id": job_id}


async def run_generation_pipeline(job_id: str, job_record: dict) -> None:
    """Background task that runs the full generation pipeline."""
    from app.services import IngestionService, GenerationService
    from app.services.compilation_service import CompilationService
    from app.services.pdf_rendering_service import PDFRenderingService
    from app.services.storage_service import StorageService

    try:
        # Step 1: Ingestion - ONLY run if document is not already indexed
        # For the standard /generate endpoint, we assume it's already ingested.
        # If we find the document is missing from vector store, we could re-ingest,
        # but typically this endpoint should skip straight to generation.

        job_record["status"] = "generating"
        job_record["current_step"] = "generation"
        job_record["progress_percentage"] = 40

        job_record["status"] = "generating"
        job_record["current_step"] = "generation"
        job_record["progress_percentage"] = 40

        # Step 2: Generation — retrieve context, then generate questions
        from app.services import SearchService
        search = SearchService()
        generation = GenerationService()
        try:
            # Retrieve context from indexed chunks
            spec = job_record["specification"]
            query = f"{spec.get('subject', '')} {spec.get('title', '')}"
            search_results = await search.hybrid_search(
                query=query,
                document_id=job_record["source_document_id"],
                top_k=5,
            )
            # Convert to (content, metadata) tuples for the agent
            from app.services.ingestion_service import ChunkMetadata
            context_chunks = []
            for r in search_results:
                meta = ChunkMetadata(
                    chapter=r.chapter,
                    topic=r.topic,
                    page_range=(r.page_start, r.page_end) if r.page_start else None,
                    heading_path=r.heading_path,
                )
                context_chunks.append((r.content, meta))

            logger.info("Retrieved %d context chunks", len(context_chunks))

            result = await generation.generate_questions(
                job_id=job_record["job_id"],
                specification=spec,
                context_chunks=context_chunks,
            )
        finally:
            await search.close()
            await generation.close()

        # Update status: validating
        job_record["status"] = "validating"
        job_record["current_step"] = "validation"
        job_record["progress_percentage"] = 70

        # Step 3: Compilation
        compiler = CompilationService()
        compiled = compiler.compile(
            questions=result.questions,
            specification=job_record["specification"],
            job_id=job_id,
            tenant_id=job_record["tenant_id"],
        )

        # Update status: review_pending
        job_record["status"] = "review_pending"
        job_record["current_step"] = "review"
        job_record["progress_percentage"] = 90
        job_record["question_paper"] = compiled.question_paper
        job_record["answer_key"] = compiled.answer_key
        job_record["validation_summary"] = json.dumps(result.validation_summary)

        # Step 4: Render PDFs & Markdown
        from pathlib import Path
        data_dir = Path("data")
        data_dir.mkdir(parents=True, exist_ok=True)
        from app.services.markdown_rendering_service import MarkdownRenderingService
        md_renderer = MarkdownRenderingService()
        renderer = PDFRenderingService()
        try:
            # 1. Generate Markdown (Primary)
            question_paper_md = md_renderer.render_question_paper(compiled.question_paper)
            answer_key_md = md_renderer.render_answer_key(compiled.answer_key)

            question_paper_md_path = data_dir / f"{job_id}_question_paper.md"
            answer_key_md_path = data_dir / f"{job_id}_answer_key.md"
            question_paper_md_path.write_text(question_paper_md, encoding="utf-8")
            answer_key_md_path.write_text(answer_key_md, encoding="utf-8")

            job_record["question_paper_md_url"] = str(question_paper_md_path)
            job_record["answer_paper_md_url"] = str(answer_key_md_path)

            # 2. Generate PDF (Optional/Fallback)
            question_paper_pdf = await renderer.render_question_paper(compiled.question_paper)
            answer_key_pdf = await renderer.render_answer_key(compiled.answer_key)
            question_paper_path = data_dir / f"{job_id}_question_paper.pdf"
            answer_key_path = data_dir / f"{job_id}_answer_key.pdf"
            question_paper_path.write_bytes(question_paper_pdf)
            answer_key_path.write_bytes(answer_key_pdf)

            job_record["question_paper_url"] = str(question_paper_path)
            job_record["answer_paper_url"] = str(answer_key_path)
        except Exception as render_error:
            logger.warning("Rendering failed for job %s: %s", job_id, render_error)

        logger.info("Job %s generation complete, pending review", job_id)

    except Exception as e:
        logger.error("Job %s failed: %s", job_id, str(e), exc_info=True)
        job_record["status"] = "failed"
        # Surface a more actionable message for the common case of a corrupt PDF.
        if "CorruptPDFError" in type(e).__name__ or "corrupt" in str(e).lower():
            job_record["error_message"] = (
                f"The PDF appears to be corrupt at the binary level: {e}. "
                "Please provide a clean copy of the source PDF (the existing "
                "file has had its non-UTF-8 bytes mangled, likely by a file "
                "sync or transfer process)."
            )
        else:
            job_record["error_message"] = str(e)
        job_record["current_step"] = "failed"