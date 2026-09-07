"""Generate a random (but schema-valid) Specification JSON for testing.

Matches app/schemas/specification.py: Specification. Topics default to the
three chapters in data/sample-maths.pdf (Algebra, Calculus, Geometry) so the
output is usable against the bundled sample PDF out of the box — pass
--topics to point it at your own document instead.

Usage:
    python scripts/generate_random_spec.py
    python scripts/generate_random_spec.py --seed 42 -o my_spec.json
    python scripts/generate_random_spec.py --topics "Photosynthesis" "Cell Division" "Genetics"
"""

import argparse
import json
import random
import string
from pathlib import Path

QUESTION_TYPES = [
    "multiple_choice",
    "short_answer",
    "long_answer",
    "problem_solving",
    "essay",
]
DIFFICULTIES = ["easy", "medium", "hard"]

PROMPT_TEMPLATES = {
    "multiple_choice": "Generate a multiple-choice question on {topic} at {difficulty} difficulty, with 4 options and exactly one correct answer.",
    "short_answer": "Generate a short-answer question on {topic} at {difficulty} difficulty, answerable in 2-3 sentences.",
    "long_answer": "Generate a long-answer question on {topic} at {difficulty} difficulty requiring a detailed, multi-step explanation.",
    "problem_solving": "Generate a problem-solving question on {topic} at {difficulty} difficulty that requires applying a formula or method to reach a numeric answer.",
    "essay": "Generate an essay-style question on {topic} at {difficulty} difficulty that asks the student to compare, contrast, or critically evaluate a concept.",
}


def random_spec(topics: list[str], seed: int | None = None) -> dict:
    rng = random.Random(seed)

    question_count = rng.randint(5, 8)
    marks_per_question = [rng.choice([2, 5, 10]) for _ in range(question_count)]
    total_marks = sum(marks_per_question)

    questions = []
    for marks in marks_per_question:
        topic = rng.choice(topics)
        q_type = rng.choice(QUESTION_TYPES)
        difficulty = rng.choice(DIFFICULTIES)
        questions.append(
            {
                "question_type": q_type,
                "topic": topic,
                "difficulty_level": difficulty,
                "estimated_time_minutes": rng.choice([3, 5, 8, 10, 15]),
                "marks": marks,
                "prompt_template": PROMPT_TEMPLATES[q_type].format(
                    topic=topic, difficulty=difficulty
                ),
            }
        )

    # Build a category distribution consistent with the questions actually generated
    category_distribution = []
    for topic in topics:
        topic_questions = [q for q in questions if q["topic"] == topic]
        if not topic_questions:
            continue
        n = len(topic_questions)
        marks_sum = sum(q["marks"] for q in topic_questions)
        category_distribution.append(
            {
                "category_name": topic,
                "min_questions": max(1, n - 1),
                "max_questions": n + 1,
                "min_marks": max(1, marks_sum - 5),
                "max_marks": marks_sum + 5,
            }
        )

    duration_minutes = sum(q["estimated_time_minutes"] for q in questions) + rng.choice([10, 15, 20])
    suffix = "".join(rng.choices(string.ascii_uppercase + string.digits, k=4))

    return {
        "title": f"{rng.choice(topics)} Practice Test ({suffix})",
        "subject": "Mathematics",
        "academic_year": "2026",
        "duration_minutes": duration_minutes,
        "total_marks": total_marks,
        "question_count": question_count,
        "category_distribution": category_distribution,
        "mark_distribution": {
            "total_marks": total_marks,
            "negative_marking_enabled": rng.choice([True, False]),
            "negative_mark_weight": rng.choice([0.0, 0.25, 0.5]),
            "pass_mark": round(total_marks * 0.4),
        },
        "questions": questions,
        "metadata": {"generated_by": "generate_random_spec.py", "random_seed": seed},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--topics",
        nargs="+",
        default=["Algebra", "Calculus", "Geometry"],
        help="Topics to draw questions from (default: matches data/sample-maths.pdf)",
    )
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    parser.add_argument(
        "-o", "--output", default="sample_specification.json", help="Output JSON file path"
    )
    args = parser.parse_args()

    spec = random_spec(args.topics, seed=args.seed)
    Path(args.output).write_text(json.dumps(spec, indent=2))
    print(f"Wrote random specification to {args.output}")
    print(json.dumps(spec, indent=2))
