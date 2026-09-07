"""API v1 router package."""

from fastapi import APIRouter

api_router = APIRouter(prefix="/api/v1")

from . import question_papers

api_router.include_router(question_papers.router)