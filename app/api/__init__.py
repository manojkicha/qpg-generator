"""API package."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

def create_app() -> FastAPI:
    """Create the FastAPI application with all routes and middleware."""
    from app.api.v1 import api_router
    from app.core.config import settings
    from app.db import init_db, close_db

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: Initialize database tables
        await init_db()
        yield
        # Shutdown: Close database connections
        await close_db()

    app = FastAPI(
        title="Question Paper Generator API",
        description="AI-Powered Question Paper Generator — Module 1",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # Add CORS middleware to allow the frontend to communicate with the backend
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # In production, replace with ["http://localhost:8443"]
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Add API router
    app.include_router(api_router)

    # Health check
    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "environment": settings.environment}

    @app.get("/")
    async def root():
        return {
            "name": "Question Paper Generator API",
            "version": "0.1.0",
            "docs": "/docs",
        }

    return app