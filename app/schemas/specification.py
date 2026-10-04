"""Schema definitions for the AI specification."""

from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class TopicDistribution(BaseModel):
    """Distribution of questions across specific chapters/topics."""
    chapter_id: str = Field(..., description="Unique ID of the chapter (e.g., Ch_1)")
    chapter_name: str = Field(..., description="Name of the chapter")
    question_count: int = Field(ge=0, description="Number of questions to generate from this chapter")


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


class SectionSpecification(BaseModel):
    """Specification for a single section of the question paper."""
    section_id: str = Field(..., description="Unique ID of the section (e.g., Section_A)")
    section_title: str = Field(..., description="Title of the section")
    question_type: str = Field(
        ...,
        description="Type of question. Values: multiple_choice, fill_in_the_blanks, match_the_following, picture_based, very_short_answer, short_answer, long_answer"
    )
    total_questions_to_generate: int = Field(ge=1, description="Total number of questions to be generated in this section")
    mandatory_to_answer: int = Field(ge=1, description="Number of questions the student must answer")
    marks_per_question: int = Field(ge=1, description="Marks allocated to each question in this section")
    instructions: Optional[str] = Field(None, description="Specific instructions for this section (e.g., 'Answer any 3 out of 5')")
    topic_distribution: List[TopicDistribution] = Field(
        ..., description="Breakdown of questions per chapter within this section"
    )


class PaperMetadata(BaseModel):
    """High-level metadata for the question paper."""
    title: str = Field(..., description="Paper title")
    grade_level: str = Field(..., description="Grade level (e.g., Primary Level)")
    total_marks: int = Field(ge=1, description="Total marks for the entire paper")
    paper_difficulty_level: str = Field(
        default="medium",
        pattern="^(easy|medium|hard)$",
        description="Overall difficulty level"
    )


class PaperConstraints(BaseModel):
    """Global constraints for the generation process."""
    ensure_distinct_questions: bool = Field(default=True, description="Ensure no duplicate questions are generated")
    strict_chapter_mapping: bool = Field(default=True, description="Strictly adhere to the chapter mapping provided")
    avoid_overlapping_concepts_across_sections: bool = Field(default=True, description="Avoid repeating concepts in different sections")


class Specification(BaseModel):
    """Full AI specification for question paper generation."""
    paper_metadata: PaperMetadata = Field(..., description="Metadata about the paper")
    constraints: PaperConstraints = Field(default_factory=PaperConstraints, description="Global generation constraints")
    sections: List[SectionSpecification] = Field(..., description="List of sections defining the paper structure")

    @property
    def total_requested_questions(self) -> int:
        return sum(s.total_questions_to_generate for s in self.sections)

    @property
    def calculated_total_marks(self) -> int:
        return sum(s.total_questions_to_generate * s.marks_per_question for s in self.sections)


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
