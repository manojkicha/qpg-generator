"""FastAPI router for question paper generation endpoints.

Based on SDD Section 12.1 API Contract:
- POST /api/v1/question-papers/generate — start generation job
- GET /api/v1/question-papers/jobs/{jobId} — get job status
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from fastapi.responses import JSONResponse

from app.schemas import JobCreate, JobResponse, JobStatusResponse
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
        # Update status: ingesting
        job_record["status"] = "ingesting"
        job_record["current_step"] = "ingestion"
        job_record["progress_percentage"] = 10

        # Step 1: Ingestion — try a few common file locations
        ingestion = IngestionService()
        try:
            document_id = job_record["source_document_id"]
            # Try multiple paths
            candidate_paths = [
                f"data/{document_id}.pdf",
                f"data/{document_id}",
                f"data/sample-maths.pdf",  # Fallback for testing
            ]
            document_path = None
            for path in candidate_paths:
                import os
                if os.path.exists(path):
                    document_path = path
                    break

            if not document_path:
                raise FileNotFoundError(
                    f"No document found for {document_id} (tried: {candidate_paths})"
                )

            chunk_ids = await ingestion.process_document(
                document_id=document_id,
                document_path=document_path,
                page_start=job_record.get("page_start", 1),
                page_end=job_record.get("page_end"),
                ocr_dpi=job_record.get("ocr_dpi", 200),
            )
        finally:
            await ingestion.close()

        # Update status: generating
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
                document_id=document_id,
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