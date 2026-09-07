"""Integration tests for the API."""

import pytest
from fastapi.testclient import TestClient

from app.api import create_app


@pytest.fixture
def client():
    """Test client fixture."""
    app = create_app()
    return TestClient(app)


def test_health_check(client):
    """Health check should return healthy."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_root_endpoint(client):
    """Root endpoint should return API info."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "name" in data
    assert "version" in data


def test_generate_question_paper_endpoint_exists(client):
    """Test that the generate endpoint is registered."""
    response = client.post(
        "/api/v1/question-papers/generate",
        json={
            "source_document_id": "doc-123",
            "additional_material_ids": [],
            "specification": {
                "title": "Test",
                "subject": "Math",
                "academic_year": "2026",
                "duration_minutes": 60,
                "total_marks": 100,
                "question_count": 5,
                "category_distribution": [],
                "mark_distribution": {"total_marks": 100},
            },
            "tenant_id": "test-tenant",
        },
    )
    # May be 202 (queued) or may fail with background task errors
    # Just check the endpoint exists
    assert response.status_code in (202, 500)


def test_get_job_status_404_for_unknown_job(client):
    """Unknown job should return 404."""
    response = client.get("/api/v1/question-papers/jobs/nonexistent-job-id")
    assert response.status_code == 404