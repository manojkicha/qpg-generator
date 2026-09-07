"""Test suite for Question Paper Generator."""

import pytest


@pytest.fixture
def sample_specification():
    """Sample specification for testing."""
    return {
        "title": "Sample Question Paper",
        "subject": "Mathematics",
        "academic_year": "2026",
        "duration_minutes": 180,
        "total_marks": 100,
        "question_count": 5,
        "category_distribution": [
            {
                "category_name": "Algebra",
                "min_questions": 2,
                "max_questions": 3,
                "min_marks": 20,
                "max_marks": 30,
            },
            {
                "category_name": "Geometry",
                "min_questions": 2,
                "max_questions": 3,
                "min_marks": 20,
                "max_marks": 30,
            },
        ],
        "mark_distribution": {
            "total_marks": 100,
            "negative_marking_enabled": False,
        },
    }


@pytest.fixture
def sample_questions():
    """Sample generated questions for testing."""
    return [
        {
            "id": "q_1",
            "question_text": "Solve the equation x^2 - 5x + 6 = 0",
            "topic": "Algebra",
            "question_type": "problem_solving",
            "marks": 10,
            "difficulty_level": "medium",
            "estimated_time_minutes": 5,
            "answer_outline": "Factor to (x-2)(x-3)=0, so x=2 or x=3",
        },
        {
            "id": "q_2",
            "question_text": "Find the area of a circle with radius 7 cm",
            "topic": "Geometry",
            "question_type": "problem_solving",
            "marks": 10,
            "difficulty_level": "easy",
            "estimated_time_minutes": 5,
            "answer_outline": "Area = πr² = π × 49 = 49π cm²",
        },
    ]