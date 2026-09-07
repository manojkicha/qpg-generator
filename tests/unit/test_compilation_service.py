"""Tests for CompilationService."""

import pytest

from app.services.compilation_service import CompilationService


def test_compile_builds_paper_and_answer_key(sample_questions):
    """Compilation should produce valid question paper and answer key."""
    service = CompilationService()
    spec = {
        "title": "Test Paper",
        "subject": "Math",
        "academic_year": "2026",
        "duration_minutes": 60,
        "total_marks": 20,
    }

    result = service.compile(
        questions=sample_questions,
        specification=spec,
        job_id="test-job-123",
        tenant_id="test-tenant",
    )

    assert result.question_paper["title"] == "Test Paper"
    assert result.question_paper["total_questions"] == 2
    assert len(result.answer_key["answers"]) == 2
    assert result.question_paper["job_id"] == "test-job-123"


def test_compile_generates_specification_hash():
    """Each compile run should produce a deterministic spec hash."""
    service = CompilationService()
    spec = {
        "title": "Test",
        "subject": "Math",
        "academic_year": "2026",
        "duration_minutes": 60,
        "total_marks": 100,
    }
    questions = []

    result1 = service.compile(questions, spec, "job-1", "tenant-1")
    result2 = service.compile(questions, spec, "job-2", "tenant-2")

    # Same spec, different jobs — hash should be the same
    assert result1.question_paper["specification_hash"] == result2.question_paper["specification_hash"]


def test_compile_includes_negative_marking_config():
    """Compilation should respect negative marking config."""
    service = CompilationService()
    spec = {
        "title": "Test",
        "subject": "Math",
        "academic_year": "2026",
        "duration_minutes": 60,
        "total_marks": 100,
        "mark_distribution": {
            "negative_marking_enabled": True,
            "negative_mark_weight": 0.5,
        },
    }

    result = service.compile([], spec, "job-1", "tenant-1")

    assert result.answer_key["negative_marking_enabled"] is True
    assert result.answer_key["negative_marks_per_wrong"] == 0.5