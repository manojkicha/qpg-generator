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

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile, status, Request, Depends
from fastapi.responses import JSONResponse

from app.schemas import JobCreate, JobResponse, JobStatusResponse, PDFGenerationResponse
from app.schemas.specification import QuestionPaperValidationSummary
from app.core.auth.jwt_handler import validate_token

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
    job_request: JobCreate,
    background_tasks: BackgroundTasks,
    token_data: dict = Depends(validate_token),
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
        "specification": job_request.specification,
        "source_document_id": job_request.source_document_id,
        "additional_material_ids": job_request.additional_material_ids,
        "tenant_id": job_request.tenant_id,
        "page_start": job_request.page_start,
        "page_end": job_request.page_end,
        "ocr_dpi": job_request.ocr_dpi,
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
async def get_job_status(
    job_id: str,
    token_data: dict = Depends(validate_token),
) -> JobStatusResponse:
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

    # Approved jobs: link to the PDFs already in blob storage (nothing is regenerated)
    blob_urls = await _existing_blob_urls(job) if job.get("reviewed_at") else {}

    return JobStatusResponse(
        job_id=job_id,
        status=job["status"],
        current_step=job.get("current_step"),
        progress_percentage=job.get("progress_percentage", 0),
        validation_summary=validation_summary,
        question_paper_url=blob_urls.get("question_paper_pdf_bytes") or job.get("question_paper_url"),
        answer_paper_url=blob_urls.get("answer_paper_pdf_bytes") or job.get("answer_paper_url"),
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
    token_data: dict = Depends(validate_token),
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
    from app.services.reportlab_rendering_service import ReportLabRenderingService

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
        renderer = ReportLabRenderingService()

        try:
            # 1. Generate Markdown (Primary)
            question_paper_md = md_renderer.render_question_paper(compiled.question_paper)
            answer_key_md = md_renderer.render_answer_key(compiled.answer_key)

            # We no longer write these to local disk (data/)
            job_record["question_paper_md_content"] = question_paper_md
            job_record["answer_paper_md_content"] = answer_key_md

            # 2. Generate JSON (Structured Data)
            # We no longer write these to local disk (data/)
            job_record["question_paper_json_content"] = json.dumps(compiled.question_paper, indent=2)
            job_record["answer_key_json_content"] = json.dumps(compiled.answer_key, indent=2)

            # 3. Generate PDF using ReportLab (matching qpg_sample.py styling)
            # Stored separately so a failed answer key does not drop the question paper
            job_record["question_paper_pdf_bytes"] = await renderer.render_question_paper(compiled.question_paper)
            job_record["answer_paper_pdf_bytes"] = await renderer.render_answer_key(compiled.answer_key)
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
    token_data: dict = Depends(validate_token),
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

    logger.info("Created blob-URL generation job %s (blob_url=%s)", job_id, blob_url)

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
    from app.services.reportlab_rendering_service import ReportLabRenderingService

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
        renderer = ReportLabRenderingService()

        try:
            # 1. Generate Markdown (Primary)
            question_paper_md = md_renderer.render_question_paper(compiled.question_paper)
            answer_key_md = md_renderer.render_answer_key(compiled.answer_key)

            # We no longer write these to local disk (data/)
            job_record["question_paper_md_content"] = question_paper_md
            job_record["answer_paper_md_content"] = answer_key_md

            # 2. Generate JSON (Structured Data)
            # We no longer write these to local disk (data/)
            job_record["question_paper_json_content"] = json.dumps(compiled.question_paper, indent=2)
            job_record["answer_key_json_content"] = json.dumps(compiled.answer_key, indent=2)

            # 3. Generate PDF using ReportLab (matching qpg_sample.py styling)
            # Stored separately so a failed answer key does not drop the question paper
            job_record["question_paper_pdf_bytes"] = await renderer.render_question_paper(compiled.question_paper)
            job_record["answer_paper_pdf_bytes"] = await renderer.render_answer_key(compiled.answer_key)
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
    token_data: dict = Depends(validate_token),
) -> dict:
    """Human review approval endpoint.

    After generation, an admin can approve or request changes.
    Upon approval, the generated PDF files are uploaded to Azure Blob Storage
    and moved to the local 'output' directory.
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

    # Approval happens only once per job: afterwards return the already-uploaded files
    if job.get("reviewed_at"):
        logger.info("Job %s already approved; returning existing blob URLs", job_id)
        return {
            "message": "Question paper already approved; returning existing files",
            "job_id": job_id,
            "reviewed_by": job.get("reviewed_by"),
            "reviewed_at": job.get("reviewed_at"),
            "blob_urls": await _existing_blob_urls(job),
            "render_errors": {},
        }

    # Block a second request from uploading while the first is still running
    if job.get("approval_in_progress"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Approval for job {job_id} is already in progress",
        )
    job["approval_in_progress"] = True

    try:
        from app.services.storage_service import StorageService
        from app.services.reportlab_rendering_service import ReportLabRenderingService

        # Re-render any PDF that is missing (e.g. rendering failed during generation)
        renderer = ReportLabRenderingService()
        render_errors = {}
        for key, source_key, render in (
            ("question_paper_pdf_bytes", "question_paper", renderer.render_question_paper),
            ("answer_paper_pdf_bytes", "answer_key", renderer.render_answer_key),
        ):
            if job.get(key) or not job.get(source_key):
                continue
            try:
                job[key] = await render(job[source_key])
                logger.info("Re-rendered %s for job %s during approval", key, job_id)
            except Exception as render_err:
                logger.error("Failed to render %s for job %s: %s", key, job_id, render_err, exc_info=True)
                render_errors[key] = str(render_err)

        container_name = _output_container(job)
        # One UTC timestamp per job, kept across retries, e.g.
        # <job_id>/question_paper_20261017T093015Z.pdf
        version_ts = job.setdefault("version_ts", datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
        blob_names = job.setdefault("blob_names", {})
        upload_errors = {}

        storage = StorageService()
        try:
            for key, filename in _OUTPUT_FILES.items():
                if key in blob_names:
                    continue  # uploaded by an earlier, partially failed attempt
                file_data = job.get(key)
                if not file_data:
                    upload_errors[key] = render_errors.get(key, "No PDF available for this job")
                    continue
                stem, ext = filename.rsplit(".", 1)
                blob_name = f"{job_id}/{stem}_{version_ts}.{ext}"
                try:
                    await storage.upload_document(
                        container_name=container_name,
                        blob_name=blob_name,
                        data=file_data,
                    )
                    blob_names[key] = blob_name
                    logger.info("Uploaded %s to Azure container %s", blob_name, container_name)
                except Exception as upload_err:
                    logger.error("Failed to upload %s to Azure: %s", blob_name, upload_err, exc_info=True)
                    upload_errors[key] = str(upload_err)
        finally:
            await storage.close()

        # Not approved unless every file is stored, so the request can be retried
        if upload_errors:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "message": "Approval not completed: some files could not be stored. Retry the request.",
                    "errors": upload_errors,
                },
            )

        job["status"] = "completed"
        job["reviewed_by"] = reviewer
        job["reviewed_at"] = datetime.now(timezone.utc).isoformat()
        job["review_comments"] = comments
    finally:
        job["approval_in_progress"] = False

    logger.info("Job %s approved by %s", job_id, reviewer)

    return {
        "message": "Question paper approved and uploaded to Azure",
        "job_id": job_id,
        "reviewed_by": reviewer,
        "reviewed_at": job["reviewed_at"],
        "blob_urls": await _existing_blob_urls(job),
        "render_errors": render_errors,
    }


_OUTPUT_FILES = {
    "question_paper_pdf_bytes": "question_paper.pdf",
    "answer_paper_pdf_bytes": "answer_paper.pdf",
}


def _output_container(job: dict) -> str:
    return f"tenant-{job.get('tenant_id', 'default')}-outputs"


async def _existing_blob_urls(job: dict) -> dict:
    """Read URLs for a job's already-uploaded PDFs.

    Nothing is uploaded: only a new short-lived SAS link is created for the stored
    blobs, because a link saved at approval time would expire.
    """
    blob_names = job.get("blob_names") or {}
    if not blob_names:
        return {}

    from app.services.storage_service import StorageService

    storage = StorageService()
    urls = {}
    try:
        for key, blob_name in blob_names.items():
            try:
                urls[key] = await storage.get_blob_url(_output_container(job), blob_name)
            except Exception as url_err:
                logger.error("Failed to create URL for %s: %s", blob_name, url_err, exc_info=True)
    finally:
        await storage.close()
    return urls


async def run_generation_pipeline(job_id: str, job_record: dict) -> None:
    """Background task that runs the full generation pipeline."""
    from app.services import IngestionService, GenerationService
    from app.services.compilation_service import CompilationService
    from app.services.reportlab_rendering_service import ReportLabRenderingService
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
        from app.services.markdown_rendering_service import MarkdownRenderingService
        md_renderer = MarkdownRenderingService()
        renderer = ReportLabRenderingService()
        try:
            # 1. Generate Markdown (Primary)
            question_paper_md = md_renderer.render_question_paper(compiled.question_paper)
            answer_key_md = md_renderer.render_answer_key(compiled.answer_key)

            # Store content in memory instead of writing to local disk (data/)
            job_record["question_paper_md_content"] = question_paper_md
            job_record["answer_paper_md_content"] = answer_key_md

            # 2. Generate PDF (Optional/Fallback)
            # Stored separately so a failed answer key does not drop the question paper
            job_record["question_paper_pdf_bytes"] = await renderer.render_question_paper(compiled.question_paper)
            job_record["answer_paper_pdf_bytes"] = await renderer.render_answer_key(compiled.answer_key)
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
