"""Schema for chunk responses."""

from typing import Optional
from pydantic import BaseModel


class ChunkResponse(BaseModel):
    """Schema for chunk response (alias for question_paper module)."""

    id: str
    source_document_id: str
    chapter: Optional[str] = None
    topic: Optional[str] = None
    heading_path: Optional[str] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    content: str
    content_hash: str
    character_count: int
    word_count: int
    embedding_id: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True