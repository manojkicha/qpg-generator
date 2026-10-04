"""Compilation Service — assembles the final Question Paper JSON and Answer Key.

Based on SDD Section 5.2.4:
- Compiler step assembles validated questions into final structure
- Generates both Question Paper JSON and Answer Key JSON
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.models.question_paper import QuestionPaper, QuestionPaperStatus
from app.models.answer_key import AnswerKey

logger = logging.getLogger(__name__)


@dataclass
class CompiledPaper:
    """Result of compilation."""

    question_paper: dict[str, Any]
    answer_key: dict[str, Any]
    compiled_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class CompilationService:
    """Assembles validated questions into final question paper and answer key."""

    def compile(
        self,
        questions: list[dict],
        specification: dict,
        job_id: str,
        tenant_id: str,
    ) -> CompiledPaper:
        """Compile questions into final paper structure.

        Assembles:
        - Question Paper JSON with sectional structure, metadata, spec hash
        - Answer Key JSON with correct answers, scoring rubric
        """
        logger.info("Compiling %d questions for job %s", len(questions), job_id)

        # Ensure specification is a dict
        if hasattr(specification, "model_dump"):
            spec_dict = specification.model_dump()
        elif isinstance(specification, dict):
            spec_dict = specification
        else:
            spec_dict = {}

        # Extract Metadata
        meta = spec_dict.get("paper_metadata", {})

        # Group questions by section based on the specification order
        spec_sections = spec_dict.get("sections", [])
        ordered_sections = []

        for s_spec in spec_sections:
            s_title = s_spec.get("section_title", "General Section")
            s_id = s_spec.get("section_id")
            instructions = s_spec.get("instructions", "")

            # Filter questions that belong to this section
            section_questions = [q for q in questions if q.get("section_title") == s_title]

            if section_questions:
                # Calculate marks summary for the actual generated questions
                # (Usually count x marks, but let's be dynamic)
                count = len(section_questions)
                marks_per = section_questions[0].get("marks", 0)
                summary = f"{count} x {marks_per} = {count * marks_per} Marks"

                ordered_sections.append({
                    "section_id": s_id,
                    "section_title": s_title,
                    "instructions": instructions,
                    "marks_summary": summary,
                    "questions": section_questions
                })

        # Build question paper
        question_paper = {
            "job_id": job_id,
            "tenant_id": tenant_id,
            "title": meta.get("title", "Generated Question Paper"),
            "grade_level": meta.get("grade_level", "General"),
            "total_marks": meta.get("total_marks", 100),
            "paper_difficulty_level": meta.get("paper_difficulty_level", "medium"),
            "total_questions": len(questions),
            "logo_url": spec_dict.get("logo_url", "static/images/default_logo.png"),
            "general_instructions": spec_dict.get("general_instructions", [
                "Read all questions carefully before answering.",
                "All questions are compulsory.",
                "Ensure your handwriting is neat and legible."
            ]),
            "version": 1,
            "specification_hash": self._hash_specification(spec_dict),
            "questions": self._format_questions_for_paper(questions),
            "sections": ordered_sections,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "metadata": spec_dict.get("metadata", {}),
        }

        # DEBUG: Print final JSON payload for PDF generation
        # print("\n" + "="*50 + "\nFINAL PDF JSON PAYLOAD\n" + "="*50)
        # print(json.dumps(question_paper, indent=2))
        # print("="*50 + "\n")

        # Build answer key
        answer_key = {
            "job_id": job_id,
            "question_paper_id": f"qp_{job_id}",
            "tenant_id": tenant_id,
            "total_questions": len(questions),
            "total_marks": meta.get("total_marks", 100),
            "negative_marking_enabled": spec_dict.get(
                "mark_distribution", {}
            ).get("negative_marking_enabled", False),
            "negative_marks_per_wrong": spec_dict.get(
                "mark_distribution", {}
            ).get("negative_mark_weight", 0.25),
            "answers": self._format_answers_for_key(questions),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        return CompiledPaper(
            question_paper=question_paper,
            answer_key=answer_key,
        )

    def _hash_specification(self, specification: dict) -> str:
        """Create a hash of the specification for versioning."""
        import hashlib

        spec_str = json.dumps(specification, sort_keys=True)
        return hashlib.sha256(spec_str.encode()).hexdigest()[:16]

    def _format_questions_for_paper(self, questions: list[dict]) -> list[dict]:
        """Format questions for the question paper JSON."""
        formatted = []
        for i, q in enumerate(questions):
            formatted.append(
                {
                    "id": q.get("id", f"q_{i+1}"),
                    "question_text": q.get("question_text", ""),
                    "options": q.get("options", []),
                    "topic": q.get("topic", ""),
                    "chapter_id": q.get("chapter_id"),
                    "question_type": q.get("question_type", "short_answer"),
                    "marks": q.get("marks", 10),
                    "difficulty_level": q.get("difficulty_level", "medium"),
                    "estimated_time_minutes": q.get("estimated_time_minutes", 5),
                    "prompt_used": q.get("prompt_used", ""),
                    "validation_passed": q.get("validation_passed", True),
                }
            )
        return formatted

    def _format_answers_for_key(self, questions: list[dict]) -> list[dict]:
        """Format answers for the answer key JSON."""
        answers = []
        for i, q in enumerate(questions):
            # For open-ended questions, the answer key might include marking scheme
            answer = {
                "question_id": q.get("id", f"q_{i+1}"),
                "question_text": q.get("question_text", ""),
                "marks": q.get("marks", 10),
                "answer_outline": q.get("answer_outline", ""),
                "marking_scheme": q.get("marking_scheme", {}),
                "sample_answer": q.get("sample_answer", ""),
            }
            answers.append(answer)
        return answers
