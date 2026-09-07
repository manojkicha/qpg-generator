"""Generation Service — manages the LangGraph agentic generation pipeline.

Based on SDD Section 5.2.2:
- Agentic Generation Pipeline (LangGraph) modeled as explicit graph of agent nodes
- Each step's output validated before moving to next
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from app.models.job import Job, JobStatus

logger = logging.getLogger(__name__)


class GenerationOutput:
    """Result from the generation pipeline."""

    def __init__(
        self,
        questions: list[dict],
        validation_summary: dict,
        generated_at: datetime,
        agent_trace: Optional[list[dict]] = None,
    ):
        self.questions = questions
        self.validation_summary = validation_summary
        self.generated_at = generated_at
        self.agent_trace = agent_trace or []


class GenerationService:
    """Orchestrates the LangGraph-based question generation pipeline."""

    def __init__(self) -> None:
        self._pipeline: Optional["GenerationPipeline"] = None  # type: ignore

    async def get_pipeline(self) -> "GenerationPipeline":
        """Get or create the LangGraph pipeline."""
        if self._pipeline is None:
            from app.agents.generation_graph import create_generation_graph
            self._pipeline = await create_generation_graph()
        return self._pipeline

    async def generate_questions(
        self,
        job_id: str,
        specification: dict,
        context_chunks: list[dict],
        job: Optional[Job] = None,
    ) -> GenerationOutput:
        """Run the agentic generation pipeline for a job."""
        logger.info("Starting generation for job %s", job_id)

        pipeline = await self.get_pipeline()

        # Invoke the LangGraph pipeline
        result = await pipeline.ainvoke(
            {
                "job_id": job_id,
                "specification": specification,
                "context_chunks": context_chunks,
            }
        )

        return GenerationOutput(
            questions=result.get("questions", []),
            validation_summary=result.get("validation_summary", {}),
            generated_at=datetime.now(timezone.utc),
            agent_trace=result.get("agent_trace", []),
        )

    async def close(self) -> None:
        """Clean up resources."""
        self._pipeline = None