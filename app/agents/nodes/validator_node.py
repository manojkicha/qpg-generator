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

        spec_obj = state.get("specification", {})
        if hasattr(spec_obj, "model_dump"):
            spec = spec_obj.model_dump()
        elif isinstance(spec_obj, dict):
            spec = spec_obj
        else:
            spec = {}

        logger.info("Validating %d questions", len(questions))

        validation_results = []
        for q in questions:
            issues = self._check_question(q, spec)
            validation_results.append({
                "question": q,
                "issues": issues,
                "passed": len(issues) == 0,
            })

        # Sectional and Global Integrity Check
        integrity_issues = self._check_overall_integrity(questions, spec)

        # If there are global integrity issues, we mark all as failed or flag them
        # For this implementation, we add integrity issues to each question for visibility
        for r in validation_results:
            if integrity_issues:
                r["issues"].extend(integrity_issues)
                r["passed"] = False

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

    def _check_overall_integrity(self, questions: list[dict], spec: dict) -> list[str]:
        """Checks if the overall generated set matches the section/chapter specs."""
        issues = []
        sections_spec = spec.get("sections", [])
        if not sections_spec:
            return issues

        # 1. Validate Total Marks
        meta = spec.get("paper_metadata", {})
        expected_total_marks = meta.get("total_marks", 0)
        actual_total_marks = sum(q.get("marks", 0) for q in questions)
        if expected_total_marks > 0 and actual_total_marks != expected_total_marks:
            issues.append(f"Total marks mismatch: expected {expected_total_marks}, got {actual_total_marks}")

        # 2. Validate Sectional Counts
        for s_spec in sections_spec:
            s_id = s_spec.get("section_id")
            s_title = s_spec.get("section_title")
            expected_count = s_spec.get("total_questions_to_generate", 0)

            # Count questions assigned to this section
            actual_count = sum(1 for q in questions if q.get("section_title") == s_title)
            if actual_count != expected_count:
                issues.append(f"Section {s_title} count mismatch: expected {expected_count}, got {actual_count}")

            # 3. Validate Chapter Distribution within Section
            topic_dist = s_spec.get("topic_distribution", [])
            for dist in topic_dist:
                c_id = dist.get("chapter_id")
                c_name = dist.get("chapter_name")
                expected_c_count = dist.get("question_count", 0)

                actual_c_count = sum(
                    1 for q in questions
                    if q.get("section_title") == s_title and (q.get("chapter_id") == c_id or q.get("topic") == c_name)
                )
                if actual_c_count != expected_c_count:
                    issues.append(f"Chapter {c_name} ({c_id}) in {s_title} count mismatch: expected {expected_c_count}, got {actual_c_count}")

        return issues

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

        # Check that marks are consistent with section spec
        if marks is not None:
            section_title = question.get("section_title")
            sections = spec.get("sections", [])
            matching_section = next((s for s in sections if s.get("section_title") == section_title), None)
            if matching_section:
                expected_marks = matching_section.get("marks_per_question")
                if expected_marks and marks != expected_marks:
                    issues.append(f"Marks ({marks}) mismatch with section spec ({expected_marks})")

        # Validate 'Match the Following' format
        if question.get("question_type") == "match_the_following":
            options = question.get("options", [])
            if not options or not isinstance(options, list):
                issues.append("Match the following must have a list of options")
            elif not all(isinstance(opt, dict) and "left" in opt and "right" in opt for opt in options):
                issues.append("Match the following options must be a list of objects with 'left' and 'right' keys")

        # Validate 'Fill in the Blanks' (and others) have NO options
        no_options_types = ["fill_in_the_blank", "short_answer", "long_answer", "one_word_answer", "essay"]
        if question.get("question_type") in no_options_types:
            options = question.get("options", [])
            if options and len(options) > 0:
                issues.append(f"Question type {question.get('question_type')} should not have options")

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
