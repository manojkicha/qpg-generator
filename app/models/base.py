"""Central Declarative Base for all SQLAlchemy models."""

from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    """Base class for all models to ensure they share the same metadata."""
    pass
