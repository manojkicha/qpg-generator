"""Generator Agent Node — generates individual questions using LLM with context from retrieval."""

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.prompts import build_grade_context, build_question_type_instruction

logger = logging.getLogger(__name__)


class GeneratorNode:
    """Generates individual questions based on the generation plan."""

    SYSTEM_PROMPT = """You are a question generation agent. Given a topic, question type,
difficulty level, and context from source material, generate a high-quality question.

The generated question must include these JSON keys:
- question_text: The full question text
- topic: The topic/subject area
- question_type: One of short_answer, long_answer, essay, problem_solving, multiple_choice,
  fill_in_the_blank, true_false, picture_based_mcq, match_the_following,
  one_word_answer, tick_the_correct, draw_and_label
- difficulty_level: easy, medium, or hard
- marks: A positive integer
- estimated_time_minutes: Reasonable time to answer
- answer_outline: Brief outline of expected answer
- sample_answer: A complete, model answer (when the question is open-ended)
- marking_scheme: An object with point allocations per answer element, e.g.
  {"key_point_1": 1, "example": 1}

QUALITY RULES (apply to ALL questions):
- Do NOT generate "all of the above" or "none of the above" style questions
- Ensure the question is unambiguous and has a well-defined answer
- Each question should have marks consistent with its difficulty level
- Use context from the provided source chunks to ensure factual accuracy
- Output ONLY the JSON object — no prose before or after, no markdown fences"""

    def __init__(self, llm: Any) -> None:
        self.llm = llm

    async def execute(self, state: dict) -> dict:
        """Execute the generation step for a single question.

        Args:
            state: Contains 'task_assignment', 'context_chunks', 'specification'

        Returns:
            Updated state with the generated question
        """
        task = state.get("task_assignment", {})
        context_chunks = state.get("context_chunks", [])
        specification = state.get("specification", {})

        question_type = task.get("question_type", "short_answer")
        topic = task.get("topic", "")
        difficulty = task.get("difficulty_level", "medium")
        marks = task.get("marks", 10)
        estimated_time = task.get("estimated_time_minutes", 5)

        logger.info(
            "Generating question: type=%s, topic=%s, diff=%s, marks=%d",
            question_type, topic, difficulty, marks
        )

        # Select relevant context
        relevant_context = self._select_context(context_chunks, topic)

        # Build the grade-aware context block
        grade_ctx = build_grade_context(specification)
        # Build the per-question-type formatting instructions
        type_inst = build_question_type_instruction(question_type)

        messages = [
            SystemMessage(content=self.SYSTEM_PROMPT),
            HumanMessage(content=(
                f"{grade_ctx}\n\n"
                f"QUESTION-TYPE-SPECIFIC INSTRUCTIONS ({question_type}):\n{type_inst}\n\n"
                f"Generate ONE question with the following parameters:\n\n"
                f"  Question Type: {question_type}\n"
                f"  Topic: {topic}\n"
                f"  Difficulty: {difficulty}\n"
                f"  Marks: {marks}\n"
                f"  Estimated Time: {estimated_time} minutes\n\n"
                f"  Source Context (use to ensure accuracy):\n"
                f"  {relevant_context if relevant_context else 'No source context provided'}\n\n"
                f"  Return ONLY a JSON object with these keys:\n"
                f"  question_text, topic, question_type, difficulty_level, marks,\n"
                f"  estimated_time_minutes, answer_outline, sample_answer, marking_scheme"
            )),
        ]

        response = await self.llm.ainvoke(messages)

        # Parse JSON from response
        try:
            import json
            response_text = response.content
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0]

            question_data = json.loads(response_text.strip())
        except Exception as e:
            logger.warning("Failed to parse question JSON: %s", e)
            question_data = {
                "question_text": (response.content[:500] if response.content else ""),
                "topic": topic,
                "question_type": question_type,
                "difficulty_level": difficulty,
                "marks": marks,
                "estimated_time_minutes": estimated_time,
                "answer_outline": "",
                "sample_answer": "",
                "marking_scheme": {},
            }

        # Backfill any missing fields so downstream consumers can rely on the shape
        question_data.setdefault("topic", topic)
        question_data.setdefault("question_type", question_type)
        question_data.setdefault("difficulty_level", difficulty)
        question_data.setdefault("marks", marks)
        question_data.setdefault("estimated_time_minutes", estimated_time)
        question_data.setdefault("answer_outline", "")
        question_data.setdefault("sample_answer", "")
        question_data.setdefault("marking_scheme", {})

        return {
            "generated_question": question_data,
            "agent_trace": state.get("agent_trace", []) + [
                {"agent": "generator", "status": "completed", "question_id": task.get("id")}
            ],
        }

    @staticmethod
    def _select_context(chunks: list, topic: str) -> str:
        """Select relevant chunks for the given topic."""
        if not chunks:
            return ""

        # Filter chunks by topic if possible
        relevant = []
        for chunk_text, metadata in chunks:
            if metadata.topic and topic.lower() in metadata.topic.lower():
                relevant.append(chunk_text)

        # If no topic-specific chunks, use all
        if not relevant:
            relevant = [chunk_text for chunk_text, _ in chunks[:3]]

        return "\n\n".join(relevant[:5])