"""Validator Agent Node — validates generated questions against specification rules."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ValidatorNode:
    """Validates generated questions and determines if they need to be regenerated."""

    def __init__(self, llm: Any = None) -> None:
        self.llm = llm

    async def execute(self, state: dict) -> dict:
        """Execute validation step.

        Args:
            state: Contains 'generated_question' and optionally 'questions' for batch validation

        Returns:
            Updated state with validation results and pass/fail flag
        """
        questions = state.get("questions", [])
        if not questions and state.get("generated_question"):
            questions = [state["generated_question"]]

        spec = state.get("specification", {})

        logger.info("Validating %d questions", len(questions))

        validation_results = []
        for q in questions:
            issues = self._check_question(q, spec)
            validation_results.append({
                "question": q,
                "issues": issues,
                "passed": len(issues) == 0,
            })

        # Determine overall validation
        all_passed = all(r["passed"] for r in validation_results)
        flags = [issue for r in validation_results for issue in r["issues"]]

        # Identify which questions need retry
        retry_indices = [
            i for i, r in enumerate(validation_results) if not r["passed"]
        ]

        # Update questions with validation status
        updated_questions = []
        for i, r in enumerate(validation_results):
            q = r["question"].copy()
            q["validation_passed"] = r["passed"]
            q["validation_issues"] = r["issues"]
            updated_questions.append(q)

        return {
            "questions": updated_questions,
            "validation_passed": all_passed,
            "validation_flags": flags,
            "retry_indices": retry_indices,
            "agent_trace": state.get("agent_trace", []) + [
                {
                    "agent": "validator",
                    "status": "completed",
                    "passed": all_passed,
                    "flags_count": len(flags),
                }
            ],
        }

    def _check_question(self, question: dict, spec: dict) -> list[str]:
        """Check a single question for validation issues."""
        issues: list[str] = []

        # Check required fields
        required = ["question_text", "topic", "marks", "question_type"]
        for field_name in required:
            if field_name not in question or not question[field_name]:
                issues.append(f"Missing required field: {field_name}")

        # Validate marks
        marks = question.get("marks")
        if marks is not None and (not isinstance(marks, int) or marks < 1):
            issues.append(f"Invalid marks value: {marks}")

        # Validate question text quality
        question_text = question.get("question_text", "")
        if question_text:
            issues.extend(self._check_question_quality(question_text))

        # Check that marks are consistent with spec
        if marks is not None:
            spec_total = spec.get("total_marks", 0)
            spec_count = spec.get("question_count", 0)
            if spec_count > 0 and spec_total > 0:
                # Marks per question shouldn't exceed reasonable bounds
                max_reasonable = spec_total // spec_count * 3  # Allow 3x average
                if marks > max_reasonable:
                    issues.append(
                        f"Marks ({marks}) too high relative to spec average"
                    )

        return issues

    def _check_question_quality(self, question_text: str) -> list[str]:
        """Heuristic checks for question quality."""
        issues: list[str] = []

        text_lower = question_text.lower().strip()

        # Reject 'all of the above' or 'none of the above' style
        if "all of the above" in text_lower or "none of the above" in text_lower:
            issues.append("Uses 'all/none of the above' style — discouraged")

        # Check minimum length
        if len(question_text.strip()) < 20:
            issues.append("Question text too short")

        # Check that question ends appropriately
        if not text_lower.endswith("?"):
            if not any(text_lower.startswith(w) for w in ("write", "explain", "define", "state", "list", "describe")):
                # Not a question mark and not a directive — might be missing
                pass  # Don't flag — many open-ended questions aren't questions

        return issues