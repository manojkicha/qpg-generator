"""Grade- and subject-aware prompt templates for the generation agent nodes.

The same underlying question-generation logic serves very different audiences
(Grade 1 EVS vs Class 12 Physics). These templates encode the language, scope,
and structural requirements appropriate to each level so the planner and
generator can produce age-appropriate questions.

The LLM client is provider-agnostic (Ollama, OpenAI, Azure OpenAI) — the
prompt content here is what differs by audience, not the API.
"""

from __future__ import annotations

from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# Grade profiles — keyed loosely by grade band
# ─────────────────────────────────────────────────────────────────────────────

GRADE_PROFILES: dict[str, dict] = {
    # Lower primary (Grades 1–2)
    "grade_1": {
        "label": "Grade 1 (age 6–7)",
        "audience": "young children just learning to read and write",
        "language_rules": [
            "Use very simple, short sentences (max 8–10 words).",
            "Use everyday words a 6-year-old knows (e.g., 'big', 'sun', 'water').",
            "Avoid abstract or technical terms entirely.",
            "Use playful, friendly tone — imagine a kind teacher speaking.",
            "If including any sentence in a regional language, keep it transliterated in Devanagari or Roman script only.",
        ],
        "scope_rules": [
            "Topics must be from the child's immediate environment: family, animals, plants, weather, water, food, body parts, seasons.",
            "Each question should relate to something a child can SEE, TOUCH, or DO.",
            "No multi-step reasoning — single observation or recognition only.",
        ],
        "structure_rules": [
            "For picture_based_mcq: provide exactly 3 simple options and indicate where the picture goes.",
            "For fill_in_the_blank: blank must be a single common word, not a phrase.",
            "For true_false: statement should be unambiguously true or false from a child's experience.",
            "For match_the_following: maximum 4 pairs, items from the same theme (e.g., animal → its home, fruit → its colour).",
        ],
        "marks_per_question": 1,  # typically 1 mark each at this level
    },
    "grade_2": {
        "label": "Grade 2 (age 7–8)",
        "audience": "early primary school children",
        "language_rules": [
            "Use simple sentences (max 12–15 words).",
            "Use vocabulary familiar to a 7–8 year old.",
            "Avoid technical jargon.",
        ],
        "scope_rules": [
            "Topics from the child's world: school, neighbourhood, plants, animals, seasons, festivals, water, food.",
            "Single-step observations or comparisons allowed.",
        ],
        "structure_rules": [
            "For picture_based_mcq: 3 simple options.",
            "For fill_in_the_blank: single common word.",
            "For match_the_following: up to 5 pairs from the same theme.",
        ],
        "marks_per_question": 1,
    },
    # Upper primary (Grades 3–5)
    "grade_3_to_5": {
        "label": "Grades 3–5 (age 8–11)",
        "audience": "upper primary school children",
        "language_rules": [
            "Clear, complete sentences (max 15–20 words).",
            "Introduce subject-specific vocabulary with simple explanations.",
        ],
        "scope_rules": [
            "Topics can include science, social studies, and basic math concepts at an introductory level.",
            "Two-step reasoning is allowed for higher-difficulty questions.",
        ],
        "structure_rules": [
            "For picture_based_mcq: 4 options, one clearly correct.",
            "For fill_in_the_blank: short phrase (1–3 words).",
        ],
        "marks_per_question": 2,
    },
    # Secondary (Grades 6–10)
    "grade_6_to_10": {
        "label": "Grades 6–10 (age 11–16)",
        "audience": "secondary school students",
        "language_rules": [
            "Use precise subject vocabulary with definitions where needed.",
            "Sentences can be 20+ words when conveying complex ideas.",
        ],
        "scope_rules": [
            "Standard school curriculum topics per subject.",
            "Multi-step reasoning, application, and analysis are appropriate.",
        ],
        "structure_rules": [
            "For multiple_choice: 4 options, all plausible.",
        ],
        "marks_per_question": 3,
    },
    # Higher secondary / undergraduate
    "grade_11_plus": {
        "label": "Grades 11+ / undergraduate",
        "audience": "advanced students",
        "language_rules": [
            "Use formal academic language and precise terminology.",
            "Long, complex sentences are appropriate.",
        ],
        "scope_rules": [
            "Specialized topics; assume prerequisite knowledge.",
            "Synthesis, evaluation, and proof-based reasoning are appropriate.",
        ],
        "structure_rules": [],
        "marks_per_question": 5,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Subject-specific additions
# ─────────────────────────────────────────────────────────────────────────────

SUBJECT_ADDITIONS: dict[str, list[str]] = {
    "EVS": [  # Environmental Studies — used for Grade 1–5
        "Frame questions around observation of nature, daily life, and surroundings.",
        "Use the child's local context (Indian subcontinent assumed).",
        "Encourage caring attitudes towards plants, animals, family, and community.",
        "Avoid controversial social or political topics.",
        "Prefer concrete examples over abstract concepts.",
    ],
    "Mathematics": [
        "Use clear numerical notation; avoid wordy descriptions when a number suffices.",
        "Ensure arithmetic is correct; double-check the answer.",
        "For word problems, keep the scenario familiar and short.",
    ],
    "Science": [
        "Encourage hypothesis, observation, and conclusion patterns.",
        "Use SI units in physics and chemistry questions.",
        "For biology, use proper scientific names alongside common names on first mention.",
    ],
    "English": [
        "For reading comprehension, use age-appropriate passages.",
        "For grammar, focus on a single concept per question.",
    ],
    "Social Studies": [
        "Frame questions around maps, timelines, and concrete events.",
        "Encourage empathy and multiple perspectives in open-ended questions.",
    ],
    "Hindi": [
        "Use Devanagari script in questions where appropriate.",
        "Match the question difficulty to the learner's reading level.",
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# Question-type-specific generation instructions
# ─────────────────────────────────────────────────────────────────────────────

QUESTION_TYPE_INSTRUCTIONS: dict[str, str] = {
    "fill_in_the_blank": (
        "Write a single short sentence with EXACTLY one blank marked as '____'. "
        "The blank must be a single common word the student is expected to fill in. "
        "The complete sentence (with the answer filled in) must be factually correct."
    ),
    "true_false": (
        "Write a single short statement that is unambiguously true or false. "
        "The answer key should indicate the correct answer (True/False) and a one-line reason."
    ),
    "picture_based_mcq": (
        "Describe what picture should accompany the question (e.g., 'A picture of a dog and a cat'). "
        "Write the question stem that requires looking at the picture. "
        "Provide EXACTLY 3 options labelled (a), (b), (c), with exactly one correct answer. "
        "Keep the options short (1–3 words each)."
    ),
    "match_the_following": (
        "Provide two columns labelled 'A' and 'B' with up to 4 pairs each. "
        "Items in column B should be shuffled so they don't appear in the obvious order. "
        "Use items from the same theme (e.g., 'Animal — its sound', 'Bird — its nest')."
    ),
    "one_word_answer": (
        "Ask a question whose answer is exactly one word. "
        "Acceptable answers should be unambiguous; specify the expected answer in the answer key."
    ),
    "tick_the_correct": (
        "Provide 3 short options, ask the student to tick the correct one. "
        "Use simple language."
    ),
    "draw_and_label": (
        "Ask the student to draw a simple picture (e.g., 'Draw a plant and label its parts'). "
        "List the parts they should label in the answer key."
    ),
    "multiple_choice": (
        "Provide a question stem and EXACTLY 4 options labelled (a), (b), (c), (d). "
        "All options should be plausible, with exactly one correct answer."
    ),
    "short_answer": (
        "Ask a question that can be answered in 1–3 sentences. "
        "The answer outline should list the key points required for full marks."
    ),
    "long_answer": (
        "Ask a question that requires a paragraph-length answer (5–8 sentences). "
        "The answer outline should list the key points and any examples required."
    ),
    "essay": (
        "Ask a broad question requiring an essay-length response. "
        "The answer outline should specify the structure (introduction, body, conclusion) "
        "and key arguments to cover."
    ),
    "problem_solving": (
        "Present a problem that requires multi-step reasoning. "
        "The answer key should show each step of the solution. "
        "Verify the final numerical or logical answer is correct."
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# Builders
# ─────────────────────────────────────────────────────────────────────────────

def detect_grade_profile(specification: dict) -> str:
    """Inspect the specification and return the matching grade profile key.

    Falls back to ``grade_6_to_10`` if no clear match.
    """
    grade = specification.get("grade")
    if isinstance(grade, str):
        g = grade.lower().strip()
        if g in {"1", "grade 1", "grade_1"}:
            return "grade_1"
        if g in {"2", "grade 2", "grade_2"}:
            return "grade_2"
        if g in {"3", "4", "5", "3-5", "grade_3_to_5"}:
            return "grade_3_to_5"
        if g in {"6", "7", "8", "9", "10", "6-10", "grade_6_to_10"}:
            return "grade_6_to_10"
        if g in {"11", "12", "11+", "ug", "undergraduate", "grade_11_plus"}:
            return "grade_11_plus"

    # Heuristic from academic level metadata if present
    level = (specification.get("metadata") or {}).get("level", "")
    if isinstance(level, str):
        level = level.lower()
        if "primary" in level and "lower" in level:
            return "grade_1"
        if "primary" in level:
            return "grade_3_to_5"
        if "secondary" in level:
            return "grade_6_to_10"
        if "higher" in level or "senior" in level:
            return "grade_11_plus"

    return "grade_6_to_10"


def build_grade_context(specification: dict) -> str:
    """Build a 'grade context' block to inject into generator/planner prompts.

    The returned string is human-readable; the LLM uses it to scope language,
    vocabulary, and difficulty. Returns an empty string if no profile matches.
    """
    profile_key = detect_grade_profile(specification)
    profile = GRADE_PROFILES.get(profile_key)
    if not profile:
        return ""

    parts = [
        f"AUDIENCE PROFILE: {profile['label']}",
        f"Target audience: {profile['audience']}.",
        "",
        "LANGUAGE RULES:",
        *[f"- {r}" for r in profile["language_rules"]],
        "",
        "SCOPE RULES:",
        *[f"- {r}" for r in profile["scope_rules"]],
    ]
    if profile["structure_rules"]:
        parts += [
            "",
            "STRUCTURE RULES:",
            *[f"- {r}" for r in profile["structure_rules"]],
        ]

    # Subject additions
    subject = (specification.get("subject") or "").strip()
    if subject and subject in SUBJECT_ADDITIONS:
        parts += [
            "",
            f"SUBJECT-SPECIFIC RULES ({subject}):",
            *[f"- {r}" for r in SUBJECT_ADDITIONS[subject]],
        ]

    return "\n".join(parts)


def build_question_type_instruction(question_type: str) -> str:
    """Return the per-question-type formatting instructions, or a generic note."""
    return QUESTION_TYPE_INSTRUCTIONS.get(
        question_type,
        (
            f"Generate a '{question_type}' question. "
            "Use clear, unambiguous language and provide a complete answer outline."
        ),
    )
