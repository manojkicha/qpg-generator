"""Compiler Agent Node — compiles validated questions into final paper structure."""

import logging
from typing import Any

from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class CompilerNode:
    """Compiles validated questions into final question paper and answer key JSON."""

    def __init__(self, llm: Any = None) -> None:
        self.llm = llm

    async def execute(self, state: dict) -> dict:
        """Execute the compilation step.

        Args:
            state: Contains 'questions' (validated list), 'specification', 'job_id'

        Returns:
            Updated state with compiled 'question_paper' and 'answer_key' objects
        """
        questions = state.get("questions", [])
        spec = state.get("specification", {})
        job_id = state.get("job_id", "")
        tenant_id = state.get("tenant_id", "")

        logger.info("Compiling %d questions into final paper", len(questions))

        # Build question paper JSON
        question_paper = self._build_question_paper(questions, spec, job_id, tenant_id)
        answer_key = self._build_answer_key(questions, spec, job_id, tenant_id)

        # Validation summary
        passed_count = sum(1 for q in questions if q.get("validation_passed", True))

        validation_summary = {
            "requested_questions": len(questions),
            "generated_questions": len(questions),
            "requested_marks": spec.get("total_marks", 100),
            "generated_marks": sum(q.get("marks", 0) for q in questions),
            "flags": state.get("validation_flags", []),
            "passed_validation_count": passed_count,
        }

        return {
            "question_paper": question_paper,
            "answer_key": answer_key,
            "validation_summary": validation_summary,
            "agent_trace": state.get("agent_trace", []) + [
                {"agent": "compiler", "status": "completed", "questions_compiled": len(questions)}
            ],
        }

    def _build_question_paper(
        self, questions: list[dict], spec: dict, job_id: str, tenant_id: str
    ) -> dict:
        """Build the question paper JSON structure."""
        return {
            "job_id": job_id,
            "tenant_id": tenant_id,
            "title": spec.get("title", "Generated Question Paper"),
            "subject": spec.get("subject", "General"),
            "academic_year": spec.get("academic_year", str(datetime.now(timezone.utc).year)),
            "duration_minutes": spec.get("duration_minutes", 180),
            "total_marks": spec.get("total_marks", 100),
            "total_questions": len(questions),
            "questions": [
                {
                    "id": q.get("id", f"q_{i+1}"),
                    "question_text": q.get("question_text"),
                    "topic": q.get("topic"),
                    "question_type": q.get("question_type"),
                    "marks": q.get("marks"),
                    "difficulty_level": q.get("difficulty_level", "medium"),
                    "estimated_time_minutes": q.get("estimated_time_minutes", 5),
                    "validation_passed": q.get("validation_passed", True),
                }
                for i, q in enumerate(questions)
            ],
            "specification_hash": self._compute_spec_hash(spec),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _build_answer_key(
        self, questions: list[dict], spec: dict, job_id: str, tenant_id: str
    ) -> dict:
        """Build the answer key JSON structure."""
        neg_marking = spec.get("mark_distribution", {}).get("negative_marking_enabled", False)

        return {
            "job_id": job_id,
            "question_paper_id": f"qp_{job_id}",
            "tenant_id": tenant_id,
            "total_questions": len(questions),
            "total_marks": spec.get("total_marks", 100),
            "negative_marking_enabled": neg_marking,
            "answers": [
                {
                    "question_id": q.get("id", f"q_{i+1}"),
                    "question_text": q.get("question_text"),
                    "marks": q.get("marks"),
                    "answer_outline": q.get("answer_outline", ""),
                    "marking_scheme": q.get("marking_scheme", {}),
                    "sample_answer": q.get("sample_answer", ""),
                }
                for i, q in enumerate(questions)
            ],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _compute_spec_hash(self, spec: dict) -> str:
        """Compute a hash of the specification for versioning."""
        import hashlib
        import json

        spec_str = json.dumps(spec, sort_keys=True)
        return hashlib.sha256(spec_str.encode()).hexdigest()[:16]