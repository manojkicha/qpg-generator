"""Database configuration and session management."""

import logging
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings

logger = logging.getLogger(__name__)

def get_engine() -> AsyncEngine:
    """Create and return the async database engine."""
    return create_async_engine(
        settings.database_url,
        poolclass=NullPool,
        echo=False,
        pool_pre_ping=True,
    )

engine = get_engine()

# Async session factory
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

async def init_db() -> None:
    """Initialize database tables."""
    from app.models.document import Base as DocumentBase
    from app.models.question_paper import Base as QPBase
    from app.models.job import Base as JobBase
    from app.models.chunk import Base as ChunkBase

    # Since we have multiple Base classes (one per file in the current structure),
    # we need to create tables for each.
    async with engine.begin() as conn:
        await conn.run_sync(DocumentBase.metadata.create_all)
        await conn.run_sync(QPBase.metadata.create_all)
        await conn.run_sync(JobBase.metadata.create_all)
        await conn.run_sync(ChunkBase.metadata.create_all)

    logger.info("Database tables initialized successfully.")

async def close_db() -> None:
    """Close database connections."""
    await engine.dispose()

# Event listener for connection pool management
@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable foreign keys in SQLite (for dev/testing)."""
    assert connection_record is not None
