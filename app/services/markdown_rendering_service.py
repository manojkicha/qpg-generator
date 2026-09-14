"""Markdown Rendering Service — converts Question Paper and Answer Key JSON to Markdown files.
This serves as a high-fidelity alternative to PDF when system libraries for PDF rendering are missing.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

class MarkdownRenderingService:
    """Renders question papers and answer keys to Markdown."""

    def render_question_paper(self, paper_json: dict) -> str:
        """Render a question paper JSON to a Markdown string."""
        logger.info("Rendering question paper to Markdown: %s", paper_json.get("title"))

        rendered_at = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')

        md = []
        md.append(f"# {paper_json.get('title', 'Generated Question Paper')}\n")
        md.append(f"**Subject:** {paper_json.get('subject', 'General')}")
        md.append(f"**Academic Year:** {paper_json.get('academic_year', 'N/A')}")
        md.append(f"**Duration:** {paper_json.get('duration_minutes', 'N/A')} minutes")
        md.append(f"**Total Marks:** {paper_json.get('total_marks', 'N/A')}\n")

        md.append("---")
        md.append("### Instructions:")
        md.append("- Attempt all questions.")
        md.append("- Write your answers in the spaces provided.")
        md.append("- Show all working where applicable.")
        md.append("---\n")

        for i, q in enumerate(paper_json.get("questions", []), 1):
            md.append(f"### Question {i} [{q.get('marks', 'N/A')} marks]")
            md.append(f"{q.get('question_text', '')}\n")
            md.append("\n*(Space for answer)*\n")
            md.append("\n")

        md.append("---")
        md.append(f"*Generated on {rendered_at} | {paper_json.get('subject', 'General')}*")

        return "\n".join(md)

    def render_answer_key(self, answer_key_json: dict) -> str:
        """Render an answer key JSON to a Markdown string."""
        logger.info("Rendering answer key to Markdown for job: %s", answer_key_json.get("job_id"))

        rendered_at = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')

        md = []
        md.append("# Answer Key\n")
        md.append("**CONFIDENTIAL - FOR EXAMINER USE ONLY**\n")
        md.append(f"**Job ID:** {answer_key_json.get('job_id', 'N/A')}")
        md.append(f"**Total Questions:** {answer_key_json.get('total_questions', 'N/A')} | **Total Marks:** {answer_key_json.get('total_marks', 'N/A')}")

        if answer_key_json.get("negative_marking_enabled"):
            neg_marks = answer_key_json.get("negative_marks_per_wrong", "N/A")
            md.append(f"**Negative Marking:** {neg_marks} marks per wrong answer")

        md.append("\n---")

        for i, ans in enumerate(answer_key_json.get("answers", []), 1):
            md.append(f"### Question {i} ({ans.get('marks', 'N/A')} marks)")
            md.append(f"**Answer Outline:**\n{ans.get('answer_outline', 'No outline provided.')}\n")

            marking_scheme = ans.get("marking_scheme")
            if marking_scheme and isinstance(marking_scheme, dict):
                md.append("**Marking Scheme:**")
                for step, mark in marking_scheme.items():
                    md.append(f"- {step}: {mark} mark(s)")
                md.append("\n")
            elif marking_scheme:
                md.append(f"**Marking Scheme:**\n{marking_scheme}\n")

            md.append("\n")

        md.append("---")
        md.append(f"*Generated on {rendered_at}*")

        return "\n".join(md)
