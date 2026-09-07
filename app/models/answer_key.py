"""Answer Key model — structured answers and scoring rules for a question paper."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    Column,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase as Base_cls

class Base(Base_cls):
    pass


class QuestionType(str, Enum):
    SHORT_ANSWER = "short_answer"
    LONG_ANSWER = "long_answer"
    ESSAY = "essay"
    PROBLEM_SOLVING = "problem_solving"


class QuestionOption:
    """A single option (including correct answer) for a question."""

    def __init__(self, option_id: str, text: str, is_correct: bool = False, marks: int = 1):
        self.option_id = option_id
        self.text = text
        self.is_correct = is_correct
        self.marks = marks


class ScoringRule:
    """Scoring rules for marking a question paper."""

    def __init__(
        self,
        max_total_marks: int = 100,
        negative_marking_enabled: bool = False,
        negative_marks_for_wrong: float = 0.25,
        partial_credit_enabled: bool = True,
    ):
        self.max_total_marks = max_total_marks
        self.negative_marking_enabled = negative_marking_enabled
        self.negative_marks_for_wrong = negative_marks_for_wrong
        self.partial_credit_enabled = partial_credit_enabled


class AnswerKey(Base):
    """Structured answer key for a question paper."""

    __tablename__ = "answer_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    question_paper_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    # Question count validation
    expected_questions = Column(Integer, nullable=False)
    expected_total_marks = Column(Integer, nullable=False)

    # Answer key as JSON
    answers_json = Column(Text, nullable=False)  # Full answer key structure

    # Scoring configuration
    negative_marking_enabled = Column(Integer, default=0)  # Boolean as int
    negative_marks_per_wrong = Column(Integer, default=0)  # Scaled for DB (e.g., 25 = 0.25 marks)
    partial_credit_enabled = Column(Integer, default=1)  # Boolean as int

    # URL to downloadable answer key
    answer_key_url = Column(String(500), nullable=True)

    # Audit
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())