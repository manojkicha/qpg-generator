"""POC client: upload a PDF and specification to the QPG generator.

Usage:
    python scripts/poc_pdf_generate.py \
        --pdf data/sample-maths.pdf \
        --spec sample_specification.json \
        --tenant-id poc-tenant \
        --base-url http://localhost:8000

The script:
  1. POSTs the PDF + specification to /api/v1/question-papers/generate-from-pdf
  2. Polls /api/v1/question-papers/jobs/{jobId} until the job finishes
  3. Prints the generated question paper, answer key, and validation summary
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("poc-client")


async def main(
    pdf_path: str,
    spec_path: str,
    tenant_id: str,
    base_url: str,
    poll_interval: float = 3.0,
    max_polls: int = 60,
) -> None:
    spec = Path(spec_path).read_text()
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        # ── Step 1: Submit the PDF + specification ─────────────────────────
        logger.info("Submitting PDF %s to %s", pdf_path, base_url)
        with open(pdf_path, "rb") as f:
            files = {"file": (pdf_path.name, f, "application/pdf")}
            data = {
                "specification": spec,
                "tenant_id": tenant_id,
            }
            response = await client.post(
                f"{base_url}/api/v1/question-papers/generate-from-pdf",
                files=files,
                data=data,
            )

        if response.status_code != 202:
            logger.error("Submission failed: %s %s", response.status_code, response.text)
            sys.exit(1)

        result = response.json()
        job_id = result["job_id"]
        logger.info("Submitted job %s (document_id=%s)", job_id, result["source_document_id"])

        # ── Step 2: Poll for status ────────────────────────────────────────
        for i in range(max_polls):
            await asyncio.sleep(poll_interval)
            status_resp = await client.get(
                f"{base_url}/api/v1/question-papers/jobs/{job_id}"
            )
            if status_resp.status_code != 200:
                logger.error("Status check failed: %s %s", status_resp.status_code, status_resp.text)
                sys.exit(1)

            status = status_resp.json()
            logger.info(
                "[%d/%d] status=%s step=%s progress=%d%%",
                i + 1, max_polls, status["status"], status["current_step"], status["progress_percentage"],
            )

            if status["status"] == "completed":
                print("\n=== Generated Question Paper ===")
                print(json.dumps(status.get("question_paper_url"), indent=2))
                print(json.dumps(status.get("answer_paper_url"), indent=2))
                print("\n=== Validation Summary ===")
                print(json.dumps(status.get("validation_summary"), indent=2))
                logger.info("Job %s completed successfully", job_id)
                return

            if status["status"] == "failed":
                logger.error("Job %s failed: %s", job_id, status.get("error_message"))
                sys.exit(1)

        logger.error("Job %s did not complete within %d polls", job_id, max_polls)
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pdf", default="data/sample-maths.pdf", help="Path to the PDF to ingest")
    parser.add_argument("--spec", default="sample_specification.json", help="Path to the specification JSON")
    parser.add_argument("--tenant-id", default="poc-tenant", help="Tenant id for the generated paper")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Base URL of the QPG API")
    parser.add_argument("--poll-interval", type=float, default=3.0, help="Seconds between status polls")
    parser.add_argument("--max-polls", type=int, default=60, help="Maximum number of status polls")
    args = parser.parse_args()

    asyncio.run(main(
        pdf_path=args.pdf,
        spec_path=args.spec,
        tenant_id=args.tenant_id,
        base_url=args.base_url,
        poll_interval=args.poll_interval,
        max_polls=args.max_polls,
    ))