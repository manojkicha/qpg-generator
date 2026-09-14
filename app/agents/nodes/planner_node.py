"""Planner Agent Node — decomposes the specification into question generation tasks."""

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.prompts import build_grade_context, detect_grade_profile, GRADE_PROFILES

logger = logging.getLogger(__name__)


class PlannerNode:
    """Plans the generation tasks based on the specification."""

    SYSTEM_PROMPT = """You are a question paper planner. Given a specification for a question paper,
you must decompose it into a structured, sectional plan following a formal academic template.

The specification includes:
- Total marks and question count
- Category distribution requirements
- Overall difficulty level

Your task is to output a structured plan organized by SECTIONS.
Each section must have:
1. A Section Title (e.g., "SECTION A – CHOOSE THE CORRECT ANSWER")
2. A Marks Summary (e.g., "5 x 1 = 5 Marks")
3. A list of tasks for that section.

Example Sections:
- SECTION A: MCQs (Choose the correct answer)
- SECTION B: Fill in the blanks
- SECTION C: Match the following
- SECTION D: Answer in one word
- SECTION E: Answer the following (Descriptive)
- SECTION F: Activity / Think and Answer

Output a JSON plan with this structure:
{
  "sections": [
    {
      "section_title": "SECTION A – CHOOSE THE CORRECT ANSWER",
      "marks_summary": "5 x 1 = 5 Marks",
      "tasks": [
        {
          "id": "q1",
          "question_type": "multiple_choice",
          "topic": "Plants",
          "difficulty_level": "easy",
          "marks": 1,
          "estimated_time_minutes": 1,
          "prompt_template": "Generate an MCQ about plant parts"
        },
        ...
      ]
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
        """Execute the planning step based on the structured input JSON.

        Args:
            state: Contains 'specification' which now follows the ExamSpecification format.

        Returns:
            Updated state with 'generation_plan' containing sections and tasks.
        """
        spec = state.get("specification", {})

        # Handle the new structured JSON format
        if "exam" in spec and "sections" in spec:
            logger.info("Using structured ExamSpecification for planning: %s", spec["exam"].get("title"))

            sections = []
            all_tasks = []

            # Map user-defined question types to agent-internal types
            type_mapping = {
                "mcq": "multiple_choice",
                "fill_blank": "fill_in_the_blank",
                "match": "match_the_following",
                "one_word": "one_word_answer",
                "short_answer": "short_answer",
                "activity": "picture_based_mcq" # Mapping activity to a complex type
            }

            for i, s in enumerate(spec["sections"]):
                section_name = s.get("name", f"Section {i+1}")
                q_type = s.get("question_type", "short_answer")
                internal_type = type_mapping.get(q_type, q_type)
                count = s.get("question_count", 1)
                marks = s.get("marks_each", 1)

                # Calculate marks summary (e.g., "5 x 1 = 5 Marks")
                summary = f"{count} x {marks} = {count * marks} Marks"

                tasks = []
                for j in range(count):
                    task_id = f"q{len(all_tasks)+1}"
                    tasks.append({
                        "id": task_id,
                        "question_type": internal_type,
                        "topic": spec.get("subject", spec["exam"].get("title", "General")),
                        "difficulty_level": spec.get("difficulty_level", "medium"),
                        "marks": marks,
                        "estimated_time_minutes": 2,
                        "prompt_template": f"Generate a {internal_type} question about {spec.get('subject', 'the subject')}",
                        "section_title": section_name,
                        "marks_summary": summary
                    })

                all_tasks.extend(tasks)
                sections.append({
                    "section_title": section_name,
                    "marks_summary": summary,
                    "tasks": tasks
                })

            return {
                "generation_plan": {"sections": sections, "all_tasks": all_tasks},
                "agent_trace": state.get("agent_trace", []) + [
                    {"agent": "planner", "status": "completed", "sections_count": len(sections)}
                ],
            }

        # Fallback for old specification format
        logger.warning("Input specification does not follow structured format; using legacy planner")
        grade_ctx = build_grade_context(spec)
        profile_key = detect_grade_profile(spec)
        allowed_types = self.DEFAULT_QUESTION_TYPES.get(profile_key, [])

        messages = [
            SystemMessage(content=self.SYSTEM_PROMPT),
            HumanMessage(content=(
                f"{grade_ctx}\n\n"
                f"Allowed question types for this grade: {', '.join(allowed_types) or 'any'}\n\n"
                f"Create a generation plan for this specification:\n{spec}\n\n"
                f"Return ONLY a JSON object."
            )),
        ]

        response = await self.llm.ainvoke(messages)
        try:
            import json
            plan = json.loads(response.content)
        except:
            plan = self._synthetic_sectional_plan(spec, profile_key)

        return {
            "generation_plan": plan,
            "agent_trace": state.get("agent_trace", []) + [
                {"agent": "planner", "status": "completed"}
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

    def _synthetic_sectional_plan(self, specification: dict, profile_key: str) -> dict:
        """Fallback: build a structured sectional plan."""
        subject = specification.get("subject", "General")
        difficulty = specification.get("difficulty_level", "medium")

        sections = [
            {
                "section_title": "SECTION A – CHOOSE THE CORRECT ANSWER",
                "marks_summary": "5 x 1 = 5 Marks",
                "tasks": [
                    {"id": f"q{i+1}", "question_type": "multiple_choice", "topic": subject,
                     "difficulty_level": difficulty, "marks": 1, "estimated_time_minutes": 1,
                     "prompt_template": f"Generate an MCQ for {subject}"} for i in range(5)
                ]
            },
            {
                "section_title": "SECTION B – FILL IN THE BLANKS",
                "marks_summary": "5 x 1 = 5 Marks",
                "tasks": [
                    {"id": f"q{i+6}", "question_type": "fill_in_the_blank", "topic": subject,
                     "difficulty_level": difficulty, "marks": 1, "estimated_time_minutes": 1,
                     "prompt_template": f"Generate a fill-in-the-blank for {subject}"} for i in range(5)
                ]
            },
            {
                "section_title": "SECTION C – MATCH THE FOLLOWING",
                "marks_summary": "5 x 1 = 5 Marks",
                "tasks": [
                    {"id": "match_1", "question_type": "match_the_following", "topic": subject,
                     "difficulty_level": difficulty, "marks": 5, "estimated_time_minutes": 5,
                     "prompt_template": f"Generate a matching set of 5 items for {subject}"}
                ]
            },
            {
                "section_title": "SECTION D – ANSWER IN ONE WORD",
                "marks_summary": "5 x 1 = 5 Marks",
                "tasks": [
                    {"id": f"q{i+11}", "question_type": "one_word_answer", "topic": subject,
                     "difficulty_level": difficulty, "marks": 1, "estimated_time_minutes": 1,
                     "prompt_template": f"Generate a one-word answer question for {subject}"} for i in range(5)
                ]
            },
            {
                "section_title": "SECTION E – ANSWER THE FOLLOWING",
                "marks_summary": "3 x 2 = 6 Marks",
                "tasks": [
                    {"id": f"q{i+16}", "question_type": "short_answer", "topic": subject,
                     "difficulty_level": difficulty, "marks": 2, "estimated_time_minutes": 3,
                     "prompt_template": f"Generate a short answer question for {subject}"} for i in range(3)
                ]
            }
        ]
        return {"sections": sections}
