"""ReportLab Rendering Service — converts Question Paper and Answer Key JSON to print-ready PDFs using ReportLab.
This service replicates the exact styling from qpg_sample.py to ensure consistency.
"""

import json
import tempfile
import os
from typing import Dict, Any
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Import the build function from qpg_sample
import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
from qpg_sample import build


class ReportLabRenderingService:
    """Renders question papers and answer keys to PDF using ReportLab (matching qpg_sample.py styling)."""

    def __init__(self) -> None:
        """Initialize the ReportLab rendering service."""
        pass

    def _ensure_sections(self, paper_json: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure the paper JSON has sections format compatible with qpg_sample.py build()."""
        # If already has sections, return as-is
        if paper_json.get("sections"):
            return paper_json

        # If has flat questions, group them by question type
        if paper_json.get("questions"):
            secs, order = {}, []
            for q in paper_json["questions"]:
                k = q.get("question_type", "questions")
                if k not in secs:
                    secs[k] = {
                        "section_title": k.replace("_", " ").title(),
                        "instructions": "",
                        "questions": []
                    }
                    order.append(k)
                secs[k]["questions"].append(q)
            paper_json["sections"] = [secs[k] for k in order]

        return paper_json

    async def render_question_paper(
        self,
        paper_json: Dict[str, Any],
    ) -> bytes:
        """Render a question paper JSON to PDF bytes using ReportLab.

        Args:
            paper_json: The question paper JSON object (expected to have title, total_marks,
                       total_questions, sections, questions, etc.)

        Returns:
            PDF bytes matching the qpg_sample.py styling
        """
        logger.info("Rendering question paper: %s", paper_json.get("title"))

        try:
            # Create a temporary file for the input JSON
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_json:
                # Ensure sections format for compatibility
                paper_copy = self._ensure_sections(paper_json.copy())
                json.dump(paper_copy, temp_json, indent=2)
                temp_json_path = temp_json.name

            try:
                # Create a temporary file for the output PDF
                with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_pdf:
                    temp_pdf_path = temp_pdf.name

                try:
                    # Use the existing build function from qpg_sample.py
                    output_path, _ = build(
                        json_path=temp_json_path,
                        out_path=temp_pdf_path
                    )

                    # Read the generated PDF
                    with open(output_path, 'rb') as f:
                        pdf_bytes = f.read()

                    logger.info("Question paper PDF rendered successfully with ReportLab (%d bytes)", len(pdf_bytes))
                    return pdf_bytes

                finally:
                    # Clean up the PDF temp file
                    if os.path.exists(temp_pdf_path):
                        os.unlink(temp_pdf_path)

            finally:
                # Clean up the JSON temp file
                if os.path.exists(temp_json_path):
                    os.unlink(temp_json_path)

        except Exception as e:
            logger.error("Failed to render question paper with ReportLab: %s", e)
            raise

    async def render_answer_key(
        self,
        answer_key_json: Dict[str, Any],
    ) -> bytes:
        """Render an answer key JSON to PDF bytes using ReportLab.

        Args:
            answer_key_json: The answer key JSON object (expected to have job_id, answers,
                           total_questions, total_marks, etc.)

        Returns:
            PDF bytes
        """
        logger.info("Rendering answer key for job: %s", answer_key_json.get("job_id"))

        try:
            # Prepare the answer key data in a format compatible with qpg_sample.py
            # The build() function expects a full question paper JSON, but we need to
            # generate just the answer key portion. We'll create a minimal question paper
            # structure that includes the answer key data.

            # Extract answer key data
            answers = answer_key_json.get("answers", [])
            total_questions = answer_key_json.get("total_questions", len(answers))
            total_marks = answer_key_json.get("total_marks", sum(a.get("marks", 0) for a in answers))
            job_id = answer_key_json.get("job_id", "unknown")

            # Create a minimal question paper JSON that qpg_sample.py can use
            # We embed the answer key info in the paper
            paper_data = {
                "title": f"Answer Key - {job_id}",
                "grade_level": "",
                "total_marks": total_marks,
                "paper_difficulty_level": "easy",
                "total_questions": total_questions,
                "logo_url": answer_key_json.get("logo_url"),
                "questions": [],  # No questions needed for answer key-only rendering
                "sections": [],    # No sections needed
                "generated_at": answer_key_json.get("generated_at"),
                "answer_key_data": answer_key_json  # Pass the full answer key as metadata
            }

            # Create a temporary file for the input JSON
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_json:
                json.dump(paper_data, temp_json, indent=2)
                temp_json_path = temp_json.name

            try:
                # Create a temporary file for the output PDF
                with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_pdf:
                    temp_pdf_path = temp_pdf.name

                try:
                    # Use the existing build function from qpg_sample.py
                    output_path, n = build(
                        json_path=temp_json_path,
                        out_path=temp_pdf_path
                    )

                    # Read the generated PDF
                    with open(output_path, 'rb') as f:
                        pdf_bytes = f.read()

                    logger.info("Answer key PDF rendered successfully with ReportLab (%d bytes)", len(pdf_bytes))
                    return pdf_bytes

                finally:
                    # Clean up the PDF temp file
                    if os.path.exists(temp_pdf_path):
                        os.unlink(temp_pdf_path)

            finally:
                # Clean up the JSON temp file
                if os.path.exists(temp_json_path):
                    os.unlink(temp_json_path)

        except Exception as e:
            logger.error("Failed to render answer key with ReportLab: %s", e)
            raise