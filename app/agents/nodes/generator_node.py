"""Generator Agent Node — generates individual questions using LLM with context from retrieval."""

import logging
import json
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.prompts import build_grade_context, build_question_type_instruction

logger = logging.getLogger(__name__)


class GeneratorNode:
    """Generates individual questions based on the generation plan."""

    SYSTEM_PROMPT = """You are a question generation agent. Given a topic, question type,
difficulty level, and context from source material, generate a high-quality question.

STRICT SOURCE ADHERENCE:
- You MUST generate the question and answer based ONLY on the provided Source Context.
- DO NOT use any external knowledge or internal training data to fill in gaps.
- If the provided Source Context does not contain enough information to generate a question for the given topic or chapter, you MUST return a JSON object with an error message in the 'question_text' field.
- Every question must be directly supportable by the text provided in the Source Context.

DIVERSIFICATION & QUALITY:
- Avoid repeating concepts. If multiple questions are requested for one topic, vary the cognitive level (e.g., one on basic recall, one on conceptual understanding, one on application).
- Ensure the language is age-appropriate for the specified grade level.

STRICT FORMATTING RULES:
- For 'match_the_following': The 'options' field MUST be a list of objects with 'left' and 'right' keys.
  Example: [{\"left\": \"Sense of Sight\", \"right\": \"Eyes\"}, {\"left\": \"Sense of Smell\", \"right\": \"Nose\"}]
  DO NOT return a simple list of strings.
- For 'fill_in_the_blank', 'short_answer', 'long_answer', and 'one_word_answer': The 'options' field MUST be an empty list [].
  DO NOT provide any choices or options for these types.
- For 'picture_based' and 'picture_based_mcq':
  1. The 'question_text' should clearly describe the image required.
  2. You MUST identify a relevant image from the provided Source Context. If the context contains image references (e.g., "img_123"), use that reference in the 'image_url' field.
  3. If no specific image reference is found, provide a detailed description for an image generator in the 'image_url' field.

Your generation style, tone, and structure MUST strictly follow the format seen in the reference document 'question-paper-format_v1.pdf'.

The generated question must include these JSON keys:
- question_text: The full question text
- options: A structured list of options (Required for multiple_choice and picture_based_mcq, or a list of pairs for match_the_following, otherwise empty list [])
- topic: The topic/subject area
- question_type: One of short_answer, long_answer, essay, problem_solving, multiple_choice,
  fill_in_the_blank, true_false, picture_based_mcq, match_the_following,
  one_word_answer, tick_the_correct, draw_and_label
- difficulty_level: easy, medium, or hard
- marks: A positive integer (MUST match the provided marks exactly)
- estimated_time_minutes: Reasonable time to answer
- answer_outline: Brief outline of expected answer
- sample_answer: A complete, model answer (when the question is open-ended)
- marking_scheme: An object with point allocations per answer element, e.g.
  {\"key_point_1\": 1, \"example\": 1}
- image_url: The URL or reference to the image (Required for picture_based questions, otherwise null)
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

        # Extract constraints from the new specification format
        if hasattr(specification, "model_dump"):
            spec_dict = specification.model_dump()
        elif isinstance(specification, dict):
            spec_dict = specification
        else:
            spec_dict = {}

        constraints = spec_dict.get("constraints", {})
        strict_mapping = constraints.get("strict_chapter_mapping", False)

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
            chapter_id = task.get("chapter_id") # From New Planner
            difficulty = task.get("difficulty_level", "medium")
            marks = task.get("marks", 10)
            estimated_time = task.get("estimated_time_minutes", 5)

            logger.info("Generating question: type=%s, topic=%s, chapter=%s, diff=%s, marks=%d",
                        question_type, topic, chapter_id, difficulty, marks)

            # Modified context selection to handle strict chapter mapping
            relevant_context = self._select_context(context_chunks, topic, chapter_id, strict_mapping)

            # Use the specification object or dict for grade context
            grade_ctx = build_grade_context(specification)
            type_inst = build_question_type_instruction(question_type)

            # Diversity: track previously generated questions for this topic to avoid repetition
            previous_questions = [q["question_text"] for q in all_generated_questions if q["topic"] == topic]
            avoidance_text = ""
            if previous_questions:
                avoidance_text = "\nSTRICT ANTI-REPETITION RULE: The following questions have already been generated for this topic. You MUST NOT generate any question that is similar in concept, phrasing, or answer to these:\n" + "\n".join([f"- {q}" for q in previous_questions])
                avoidance_text += "\nGenerate a completely unique question focusing on a different aspect of the topic."

            messages = [
                SystemMessage(content=self.SYSTEM_PROMPT),
                HumanMessage(content=(
                    f"{grade_ctx}\n\n"
                    f"QUESTION-TYPE-SPECIFIC INSTRUCTIONS ({question_type}):\n{type_inst}\n\n"
                    f"Generate ONE question with the following parameters:\n\n"
                    f"  Question Type: {question_type}\n"
                    f"  Topic: {topic}\n"
                    f"  Chapter ID: {chapter_id if chapter_id else 'N/A'}\n"
                    f"  Difficulty: {difficulty}\n"
                    f"  Marks: {marks}\n"
                    f"  Estimated Time: {estimated_time} minutes\n\n"
                    f"  Source Context (use to ensure accuracy):\n"
                    f"  {relevant_context if relevant_context else 'No source context provided'}\n\n"
                    f"{avoidance_text}\n\n"
                    f"  Return ONLY a JSON object with these keys:\n"
                    f"  question_text, options, topic, question_type, difficulty_level, marks,\n"
                    f"  estimated_time_minutes, answer_outline, sample_answer, marking_scheme, image_url"
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

            # --- DATA NORMALIZATION ---
            # 1. Enforce strict options for specific types
            no_options_types = ["fill_in_the_blank", "short_answer", "long_answer", "one_word_answer", "essay"]
            if question_data.get("question_type") in no_options_types:
                question_data["options"] = []

            # 2. Ensure Match the Following is in the correct object format for the renderer
            if question_data.get("question_type") == "match_the_following":
                options = question_data.get("options", [])
                if options and isinstance(options[0], str):
                    # LLM returned a simple list of strings, convert to objects
                    logger.info("Normalizing match_the_following options from list to objects")
                    normalized_options = []
                    for i in range(0, len(options), 2):
                        left = options[i]
                        right = options[i+1] if i+1 < len(options) else "N/A"
                        normalized_options.append({"left": left, "right": right})
                    question_data["options"] = normalized_options
                elif not options:
                    # If empty, provide a template to avoid empty rendering in PDF
                    question_data["options"] = [{"left": "Column A", "right": "Column B"}]
                elif not isinstance(options, list):
                    question_data["options"] = []

            # 3. Image URL handling for picture-based questions
            if "picture" in question_data.get("question_type", "").lower():
                # Try to find an image reference in the source context
                # The context is a string, look for patterns like img_123 or similar
                import re
                image_refs = re.findall(r'img_\d+', relevant_context)
                if image_refs:
                    # Use the first relevant image reference found in the context
                    question_data["image_url"] = image_refs[0]
                    logger.info("Assigned image reference %s to picture-based question", image_refs[0])
                elif not question_data.get("image_url"):
                    # Fallback to the description provided by LLM if no reference exists
                    # but ensures the field is not null
                    question_data["image_url"] = question_data.get("question_text", "No image reference found")

            # Backfill and attach section info for the PDF renderer
            question_data.setdefault("topic", topic)
            question_data.setdefault("question_type", question_type)
            question_data.setdefault("difficulty_level", difficulty)
            question_data.setdefault("marks", marks)
            question_data.setdefault("estimated_time_minutes", estimated_time)
            question_data["section_title"] = task.get("section_title", "General")
            question_data["marks_summary"] = task.get("marks_summary", "")
            question_data["chapter_id"] = chapter_id

            all_generated_questions.append(question_data)

        return {
            "questions": all_generated_questions,
            "agent_trace": state.get("agent_trace", []) + [
                {"agent": "generator", "status": "completed", "count": len(all_generated_questions)}
            ],
        }

    @staticmethod
    def _select_context(chunks: list, topic: str, chapter_id: Optional[str] = None, strict: bool = False) -> str:
        """Select relevant chunks for the given topic, with optional strict chapter filtering."""
        if not chunks:
            return ""

        relevant = []
        for item in chunks:
            # Handle both (text, metadata) tuples and metadata objects
            if isinstance(item, tuple) and len(item) == 2:
                chunk_text, metadata = item
            else:
                continue

            # 1. Strict Chapter Filtering
            if strict and chapter_id:
                cid_num = chapter_id.replace("Ch_", "")
                # Safely access attribute from ChunkMetadata dataclass
                chapter_val = getattr(metadata, "chapter", None)
                if chapter_val and cid_num in str(chapter_val):
                    relevant.append(chunk_text)
                continue

            # 2. Topic-based filtering (Fallback)
            topic_val = getattr(metadata, "topic", None)
            chapter_val = getattr(metadata, "chapter", None)

            if topic_val and topic.lower() in str(topic_val).lower():
                relevant.append(chunk_text)
            elif chapter_val and topic.lower() in str(chapter_val).lower():
                relevant.append(chunk_text)

        if not relevant:
            relevant = [item[0] for item in chunks[:3] if isinstance(item, tuple)]

        return "\n\n".join(relevant[:5])
