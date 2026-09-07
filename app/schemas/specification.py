"""Schema definitions for the AI specification."""

from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class CategoryDistribution(BaseModel):
    """Distribution of questions across categories/topics."""

    category_name: str = Field(..., description="Name of the category/topic")
    min_questions: int = Field(
        ge=0, description="Minimum number of questions from this category"
    )
    max_questions: int = Field(
        ge=0, description="Maximum number of questions from this category"
    )
    min_marks: int = Field(
        ge=0, description="Minimum total marks from this category"
    )
    max_marks: int = Field(
        ge=0, description="Maximum total marks from this category"
    )


class MarkDistribution(BaseModel):
    """Overall mark distribution for the question paper."""

    total_marks: int = Field(
        ge=1, description="Total marks the paper should contain"
    )
    negative_marking_enabled: bool = Field(
        default=False, description="Whether negative marking applies"
    )
    negative_mark_weight: float = Field(
        default=0.25,
        ge=0,
        le=1,
        description="Marks deducted per wrong answer (as fraction of correct mark value)",
    )
    pass_mark: Optional[int] = Field(
        default=None, ge=0, description="Minimum marks to pass (if applicable)"
    )


class QuestionSpecification(BaseModel):
    """Specification for a single question generation."""

    # Question type — covers both generic academic types and primary-school (Grade 1 EVS) types.
    # Valid values:
    #   Generic:  short_answer, long_answer, essay, problem_solving, multiple_choice
    #   Grade 1:  fill_in_the_blank, true_false, picture_based_mcq, match_the_following,
    #             one_word_answer, tick_the_correct, draw_and_label
    question_type: str = Field(
        ...,
        description=(
            "Type of question. Common values: short_answer, long_answer, essay, "
            "problem_solving, multiple_choice, fill_in_the_blank, true_false, "
            "picture_based_mcq, match_the_following, one_word_answer, "
            "tick_the_correct, draw_and_label"
        ),
    )
    topic: str = Field(..., description="Topic/subject area")
    difficulty_level: str = Field(
        default="medium",
        pattern="^(easy|medium|hard)$",
        description="Difficulty level",
    )
    estimated_time_minutes: int = Field(
        ge=1, default=5, description="Estimated time to answer"
    )
    marks: int = Field(ge=1, default=10, description="Marks allocated")
    prompt_template: str = Field(
        ..., description="Prompt template for the generation agent"
    )
    validation_rules: Optional[List[str]] = Field(
        default=None, description="Rules the generated question must satisfy"
    )


class Specification(BaseModel):
    """Full AI specification for question paper generation."""

    title: str = Field(..., description="Paper title")
    subject: str = Field(..., description="Subject area (e.g., Mathematics, Physics)")
    academic_year: str = Field(..., description="Academic year (e.g., 2026)")
    duration_minutes: int = Field(
        ge=1, description="Paper duration in minutes"
    )
    total_marks: int = Field(ge=1, default=100, description="Total paper marks")
    question_count: int = Field(
        ge=1, description="Number of questions to generate"
    )
    category_distribution: List[CategoryDistribution] = Field(
        default_factory=list,
        description="Distribution of questions across categories",
    )
    mark_distribution: MarkDistribution = Field(default_factory=MarkDistribution)
    questions: List[QuestionSpecification] = Field(
        default_factory=list, description="Individual question specs"
    )
    metadata: Optional[dict] = Field(
        default=None, description="Additional metadata"
    )

    @property
    def total_category_questions_min(self) -> int:
        return sum(c.min_questions for c in self.category_distribution)

    @property
    def total_category_questions_max(self) -> int:
        return sum(c.max_questions for c in self.category_distribution)


class SpecificationCreate(Specification):
    """Schema for creating a specification via API."""

    pass


class QuestionPaperValidationSummary(BaseModel):
    """Summary of validation results for a generated question paper."""

    requested_questions: int
    generated_questions: int
    requested_marks: int
    generated_marks: int
    flags: List[str] = Field(default_factory=list, description="List of validation flags")


class QuestionPaperCreate(BaseModel):
    """Schema for creating a question paper generation request."""

    source_document_id: str = Field(
        ..., description="ID of the source eBook document"
    )
    additional_material_ids: List[str] = Field(
        default_factory=list,
        description="Optional IDs of additional material documents",
    )
    specification: Specification = Field(
        ..., description="The AI specification for generation"
    )
    tenant_id: str = Field(
        ..., description="Tenant/organization identifier"
    )