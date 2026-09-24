"""Generator Agent Node — generates individual questions using LLM with context from retrieval."""

import logging
import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.prompts import build_grade_context, build_question_type_instruction

logger = logging.getLogger(__name__)


class GeneratorNode:
    """Generates individual questions based on the generation plan."""

    SYSTEM_PROMPT = """You are a question generation agent. Given a topic, question type,
difficulty level, and context from source material, generate a high-quality question.

Your generation style, tone, and structure MUST strictly follow the format seen in the reference document 'question-paper-format_v1.pdf'.

The generated question must include these JSON keys:
- question_text: The full question text
- options: A structured list of options (required for multiple_choice and picture_based_mcq, e.g., ['(a) Option 1', '(b) Option 2', ...])
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
"""

    def __init__(self, llm: Any) -> None:
        self.llm = llm

    async def execute(self, state: dict) -> dict:
        """Execute the generation step for all tasks in the plan.

        Args:
            state: Contains 'generation_plan', 'context_chunks', 'specification'

        Returns:
            Updated state with the list of generated questions
        """
        generation_plan = state.get("generation_plan", {})
        context_chunks = state.get("context_chunks", [])
        specification = state.get("specification", {})

        # Determine the list of tasks to generate
        tasks = []
        if "all_tasks" in generation_plan:
            tasks = generation_plan["all_tasks"]
        elif "sections" in generation_plan:
            for section in generation_plan["sections"]:
                for task in section.get("tasks", []):
                    tasks.append(task)
        elif "tasks" in generation_plan:
            tasks = generation_plan["tasks"]

        if not tasks:
            logger.warning("No tasks found in generation plan")
            return {"questions": [], "agent_trace": state.get("agent_trace", [])}

        all_generated_questions = []

        for task in tasks:
            question_type = task.get("question_type", "short_answer")
            topic = task.get("topic", "")
            difficulty = task.get("difficulty_level", "medium")
            marks = task.get("marks", 10)
            estimated_time = task.get("estimated_time_minutes", 5)

            logger.info("Generating question: type=%s, topic=%s, diff=%s, marks=%d",
                        question_type, topic, difficulty, marks)

            relevant_context = self._select_context(context_chunks, topic)
            grade_ctx = build_grade_context(specification)
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
                    f"  question_text, options, topic, question_type, difficulty_level, marks,\n"
                    f"  estimated_time_minutes, answer_outline, sample_answer, marking_scheme"
                )),
            ]

            try:
                response = await self.llm.ainvoke(messages)
                response_text = response.content
                if "```json" in response_text:
                    response_text = response_text.split("```json")[1].split("```")[0]
                elif "```" in response_text:
                    response_text = response_text.split("```")[1].split("```")[0]

                question_data = json.loads(response_text.strip())
            except Exception as e:
                logger.warning("Failed to generate question for %s: %s", task.get("id"), e)
                question_data = {
                    "question_text": "Error generating question.",
                    "topic": topic,
                    "question_type": question_type,
                    "difficulty_level": difficulty,
                    "marks": marks,
                    "estimated_time_minutes": estimated_time,
                    "answer_outline": "",
                    "sample_answer": "",
                    "marking_scheme": {},
                }

            # Backfill and attach section info for the PDF renderer
            question_data.setdefault("topic", topic)
            question_data.setdefault("question_type", question_type)
            question_data.setdefault("difficulty_level", difficulty)
            question_data.setdefault("marks", marks)
            question_data.setdefault("estimated_time_minutes", estimated_time)
            question_data["section_title"] = task.get("section_title", "General")
            question_data["marks_summary"] = task.get("marks_summary", "")

            all_generated_questions.append(question_data)

        return {
            "questions": all_generated_questions,
            "agent_trace": state.get("agent_trace", []) + [
                {"agent": "generator", "status": "completed", "count": len(all_generated_questions)}
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
