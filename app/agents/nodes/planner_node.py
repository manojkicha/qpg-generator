"""Planner Agent Node — decomposes the specification into question generation tasks."""

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.prompts import build_grade_context, detect_grade_profile, GRADE_PROFILES

logger = logging.getLogger(__name__)


class PlannerNode:
    """Plans the generation tasks based on the specification."""

    SYSTEM_PROMPT = """You are a question paper planner. Given a specification for a question paper,
you must decompose it into specific generation tasks for each question.

The specification includes:
- Total marks and question count
- Category distribution requirements
- Individual question specifications
- Difficulty levels

Your task is to output a structured plan that:
1. Distributes questions across categories per the specification
2. Assigns appropriate difficulty levels (mix of easy, medium, hard)
3. Ensures mark balance across the paper
4. Identifies any special requirements (e.g., diagrams, calculations, pictures)
5. Picks age-appropriate question types (e.g., fill_in_the_blank, true_false, picture_based_mcq
   for younger grades; problem_solving, essay for older grades)

Output a JSON plan with this structure:
{
  "tasks": [
    {
      "id": "q1",
      "question_type": "fill_in_the_blank",
      "topic": "Plants",
      "difficulty_level": "easy",
      "marks": 1,
      "estimated_time_minutes": 1,
      "prompt_template": "Generate a fill-in-the-blank question about plant parts for Grade 1 students"
    },
    ...
  ]
}

Return ONLY the JSON object."""

    # Default question types per grade profile if the spec doesn't pin them
    DEFAULT_QUESTION_TYPES: dict[str, list[str]] = {
        "grade_1": [
            "picture_based_mcq", "fill_in_the_blank", "true_false",
            "match_the_following", "one_word_answer", "tick_the_correct",
        ],
        "grade_2": [
            "picture_based_mcq", "fill_in_the_blank", "true_false",
            "match_the_following", "one_word_answer", "short_answer",
        ],
        "grade_3_to_5": [
            "multiple_choice", "fill_in_the_blank", "true_false",
            "short_answer", "match_the_following", "one_word_answer",
        ],
        "grade_6_to_10": [
            "multiple_choice", "short_answer", "long_answer",
            "problem_solving", "fill_in_the_blank",
        ],
        "grade_11_plus": [
            "short_answer", "long_answer", "essay", "problem_solving",
        ],
    }

    def __init__(self, llm: Any) -> None:
        self.llm = llm

    async def execute(self, state: dict) -> dict:
        """Execute the planning step.

        Args:
            state: Contains 'specification' with the question paper spec

        Returns:
            Updated state with 'generation_plan' containing task assignments
        """
        specification = state.get("specification", {})

        logger.info("Planning generation for paper: %s", specification.get("title"))

        # If the spec already enumerates individual question specifications, use them
        explicit_questions = specification.get("questions") or []
        if explicit_questions:
            plan = self._plan_from_explicit_questions(specification, explicit_questions)
            logger.info("Generated %d tasks from explicit question specs", len(plan.get("tasks", [])))
            return {
                "generation_plan": plan,
                "agent_trace": state.get("agent_trace", []) + [
                    {"agent": "planner", "status": "completed",
                     "tasks_count": len(plan.get("tasks", [])),
                     "mode": "explicit_specs"}
                ],
            }

        # Otherwise ask the LLM to plan
        grade_ctx = build_grade_context(specification)
        profile_key = detect_grade_profile(specification)
        allowed_types = self.DEFAULT_QUESTION_TYPES.get(profile_key, [])

        messages = [
            SystemMessage(content=self.SYSTEM_PROMPT),
            HumanMessage(content=(
                f"{grade_ctx}\n\n"
                f"Allowed question types for this grade: {', '.join(allowed_types) or 'any'}\n\n"
                f"Create a generation plan for this specification:\n{specification}\n\n"
                f"Return ONLY a JSON object."
            )),
        ]

        response = await self.llm.ainvoke(messages)

        # Parse the plan from the response
        try:
            import json
            plan_text = response.content
            if "```json" in plan_text:
                plan_text = plan_text.split("```json")[1].split("```")[0]
            elif "```" in plan_text:
                plan_text = plan_text.split("```")[1].split("```")[0]

            plan = json.loads(plan_text.strip())
        except Exception as e:
            logger.warning("Failed to parse plan JSON: %s", e)
            plan = {"tasks": [], "raw_response": response.content}

        # Fallback: synthesize a simple plan if LLM returned nothing usable
        if not plan.get("tasks"):
            logger.warning("Planner produced no tasks; using synthetic fallback")
            plan = self._synthetic_plan(specification, profile_key)
            logger.info("Generated %d tasks in synthetic plan", len(plan.get("tasks", [])))

        return {
            "generation_plan": plan,
            "agent_trace": state.get("agent_trace", []) + [
                {"agent": "planner", "status": "completed",
                 "tasks_count": len(plan.get("tasks", []))}
            ],
        }

    def _plan_from_explicit_questions(
        self, specification: dict, explicit_questions: list[dict]
    ) -> dict:
        """Convert spec.questions into planner task format."""
        tasks = []
        for i, q in enumerate(explicit_questions, start=1):
            tasks.append({
                "id": f"q{i}",
                "question_type": q.get("question_type", "short_answer"),
                "topic": q.get("topic", specification.get("subject", "General")),
                "difficulty_level": q.get("difficulty_level", "medium"),
                "marks": q.get("marks", 1),
                "estimated_time_minutes": q.get("estimated_time_minutes", 1),
                "prompt_template": q.get("prompt_template", ""),
            })
        return {"tasks": tasks}

    def _synthetic_plan(self, specification: dict, profile_key: str) -> dict:
        """Fallback: build a simple plan from the spec's question count + grade defaults."""
        count = specification.get("question_count", 5)
        marks = max(1, specification.get("total_marks", count) // count)
        allowed_types = self.DEFAULT_QUESTION_TYPES.get(
            profile_key, self.DEFAULT_QUESTION_TYPES["grade_6_to_10"]
        )
        # Rotate through the allowed types
        tasks = []
        for i in range(count):
            qt = allowed_types[i % len(allowed_types)]
            tasks.append({
                "id": f"q{i+1}",
                "question_type": qt,
                "topic": (specification.get("subject", "General")),
                "difficulty_level": "easy" if i < count / 3 else "medium" if i < 2 * count / 3 else "hard",
                "marks": marks,
                "estimated_time_minutes": 1 if profile_key in {"grade_1", "grade_2"} else 3,
                "prompt_template": f"Generate a {qt} question for {specification.get('subject', 'this subject')}",
            })
        return {"tasks": tasks}