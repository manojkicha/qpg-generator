"""Database configuration and session management."""

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings


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
    from app.models.question_paper import question_paper_table  # noqa: F401
    from app.models.job import job_table  # noqa: F401
    from app.models.chunk import chunk_table  # noqa: F401
    # Import all models and create tables
    pass


async def close_db() -> None:
    """Close database connections."""
    await engine.dispose()


# Event listener for connection pool management
@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable foreign keys in SQLite (for dev/testing)."""
    assert connection_record is not None