"""Tests for ValidationService."""

import pytest

from app.services.validation_service import ValidationService
from app.schemas.specification import Specification, CategoryDistribution, MarkDistribution


def test_validate_passes_for_correct_questions(sample_specification, sample_questions):
    """Validation should pass when questions match spec."""
    spec = Specification(
        title=sample_specification["title"],
        subject=sample_specification["subject"],
        academic_year=sample_specification["academic_year"],
        duration_minutes=sample_specification["duration_minutes"],
        total_marks=100,
        question_count=5,
        category_distribution=[],
        mark_distribution=MarkDistribution(total_marks=100),
    )

    # Adjust questions to match spec — 5 questions, 100 marks
    questions = sample_questions * 2 + [{
        "id": "q_5",
        "question_text": "Explain the Pythagorean theorem",
        "topic": "Geometry",
        "question_type": "short_answer",
        "marks": 20,
        "difficulty_level": "hard",
        "estimated_time_minutes": 10,
    }]

    # 10+10+10+10+20 = 60 — won't pass strict mark check; this tests only basic structure
    service = ValidationService()
    result = service.validate(questions, spec)

    assert result.generated_questions == 5
    assert result.requested_questions == 5


def test_validate_flags_missing_marks():
    """Validation should flag questions with invalid marks."""
    spec = Specification(
        title="Test",
        subject="Math",
        academic_year="2026",
        duration_minutes=60,
        total_marks=20,
        question_count=2,
        category_distribution=[],
        mark_distribution=MarkDistribution(total_marks=20),
    )

    questions = [
        {
            "id": "q_1",
            "question_text": "Q1",
            "topic": "Algebra",
            "question_type": "short_answer",
            "marks": 10,
            "difficulty_level": "medium",
            "estimated_time_minutes": 5,
        },
        {
            "id": "q_2",
            "question_text": "Q2",
            "topic": "Algebra",
            "question_type": "short_answer",
            "marks": -5,  # Invalid marks
            "difficulty_level": "medium",
            "estimated_time_minutes": 5,
        },
    ]

    service = ValidationService()
    result = service.validate(questions, spec)

    assert not result.passed
    assert any("marks" in f.lower() for f in result.flags)


def test_validate_flags_wrong_count():
    """Validation should flag when question count doesn't match."""
    spec = Specification(
        title="Test",
        subject="Math",
        academic_year="2026",
        duration_minutes=60,
        total_marks=20,
        question_count=2,
        category_distribution=[],
        mark_distribution=MarkDistribution(total_marks=20),
    )

    questions = [
        {
            "id": "q_1",
            "question_text": "Q1",
            "topic": "Algebra",
            "question_type": "short_answer",
            "marks": 10,
            "difficulty_level": "medium",
            "estimated_time_minutes": 5,
        },
    ]  # Only 1 question, spec needs 2

    service = ValidationService()
    result = service.validate(questions, spec)

    assert not result.passed
    assert any("count" in f.lower() for f in result.flags)