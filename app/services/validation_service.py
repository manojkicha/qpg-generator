"""Validation Service — validates generated questions against the specification.

Based on SDD Section 5.2.2:
- Validator Agent checks marks, question count, and category distribution
- Re-runs generation for specific questions if validation fails
"""

import logging
from dataclasses import dataclass
from typing import Optional

from app.schemas.specification import Specification

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of validating generated questions."""

    passed: bool
    flags: list[str]
    generated_questions: int
    requested_questions: int
    generated_marks: int
    requested_marks: int
    category_issues: list[str]
    retry_indices: list[int]  # Question indices to regenerate


class ValidationService:
    """Validates generated question papers against the specification."""

    def validate(
        self,
        questions: list[dict],
        specification: Specification,
    ) -> ValidationResult:
        """Validate generated questions against the specification.

        Checks:
        - Question count matches specification
        - Total marks matches specification
        - Category distribution within bounds
        - Each question has required fields
        """
        flags: list[str] = []
        category_issues: list[str] = []
        retry_indices: list[int] = []

        requested_questions = specification.question_count
        generated_questions = len(questions)
        requested_marks = specification.total_marks
        generated_marks = sum(q.get("marks", 0) for q in questions)

        # Question count validation
        if generated_questions != requested_questions:
            flags.append(
                f"Question count mismatch: requested {requested_questions}, "
                f"generated {generated_questions}"
            )
            # Identify missing/extra questions for retry
            if generated_questions < requested_questions:
                retry_indices = list(range(generated_questions, requested_questions))

        # Marks validation
        if generated_marks != requested_marks:
            flags.append(
                f"Total marks mismatch: requested {requested_marks}, "
                f"generated {generated_marks}"
            )

        # Category distribution validation
        if specification.category_distribution:
            category_issues, category_retry = self._validate_categories(
                questions, specification.category_distribution
            )
            flags.extend(category_issues)
            retry_indices.extend(category_retry)

        # Per-question validation
        for i, q in enumerate(questions):
            q_flags = self._validate_question(q)
            if q_flags:
                flags.extend([f"Question {i+1}: {f}" for f in q_flags])
                if i not in retry_indices:
                    retry_indices.append(i)

        passed = len(flags) == 0

        return ValidationResult(
            passed=passed,
            flags=flags,
            generated_questions=generated_questions,
            requested_questions=requested_questions,
            generated_marks=generated_marks,
            requested_marks=requested_marks,
            category_issues=category_issues,
            retry_indices=retry_indices,
        )

    def _validate_categories(
        self,
        questions: list[dict],
        category_distribution: list,
    ) -> tuple[list[str], list[int]]:
        """Validate that questions are distributed across categories."""
        issues: list[str] = []
        retry_indices: list[int] = []

        # Count questions per category
        category_counts: dict[str, int] = {}
        for q in questions:
            topic = q.get("topic", "unknown")
            category_counts[topic] = category_counts.get(topic, 0) + 1

        for cat in category_distribution:
            count = category_counts.get(cat.category_name, 0)
            if count < cat.min_questions:
                issues.append(
                    f"Category '{cat.category_name}': {count} questions "
                    f"(minimum {cat.min_questions})"
                )
                retry_indices.extend(
                    i for i, q in enumerate(questions)
                    if q.get("topic") == cat.category_name
                )
            if count > cat.max_questions:
                issues.append(
                    f"Category '{cat.category_name}': {count} questions "
                    f"(maximum {cat.max_questions})"
                )

        return issues, retry_indices

    def _validate_question(self, question: dict) -> list[str]:
        """Validate a single question has required fields."""
        issues: list[str] = []
        required_fields = ["question_text", "topic", "marks", "question_type"]

        for field in required_fields:
            if field not in question or not question[field]:
                issues.append(f"Missing required field: {field}")

        # Validate marks is a positive integer
        marks = question.get("marks")
        if marks is not None and (not isinstance(marks, int) or marks < 1):
            issues.append(f"Invalid marks value: {marks}")

        return issues