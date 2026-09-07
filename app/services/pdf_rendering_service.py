"""PDF Rendering Service — converts Question Paper and Answer Key JSON to print-ready PDFs.

Based on SDD Section 5.2.4:
- Renders Question Paper JSON and Answer Key JSON through templated HTML-to-PDF service
- Institution-configurable templates (header/logo, instructions, footer)
- Produces two separate, print-ready PDF files
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import jinja2

from app.core.config import settings

logger = logging.getLogger(__name__)


class PDFRenderingService:
    """Renders question papers and answer keys to PDF using HTML templates."""

    def __init__(self, templates_dir: Optional[Path] = None) -> None:
        self.templates_dir = templates_dir or Path(__file__).parent.parent / "templates"
        self._env: Optional[jinja2.Environment] = None

    @property
    def jinja_env(self) -> jinja2.Environment:
        if self._env is None:
            self._env = jinja2.Environment(
                loader=jinja2.FileSystemLoader(str(self.templates_dir)),
                autoescape=jinja2.select_autoescape(["html", "xml"]),
            )
        return self._env

    async def render_question_paper(
        self,
        paper_json: dict,
        template_name: str = "question_paper.html",
    ) -> bytes:
        """Render a question paper JSON to PDF bytes.

        Args:
            paper_json: The compiled question paper data
            template_name: Name of the Jinja2 template file

        Returns:
            PDF as bytes
        """
        logger.info("Rendering question paper: %s", paper_json.get("title"))

        try:
            from weasyprint import HTML

            template = self.jinja_env.get_template(template_name)
            html_content = template.render(
                paper=paper_json,
                rendered_at=datetime.now(timezone.utc),
            )

            pdf_bytes = HTML(string=html_content).write_pdf()
            logger.info("Question paper PDF rendered successfully")
            return pdf_bytes

        except ImportError:
            logger.warning("WeasyPrint not available, returning placeholder")
            return b"PDF_PLACEHOLDER"

    async def render_answer_key(
        self,
        answer_key_json: dict,
        template_name: str = "answer_key.html",
    ) -> bytes:
        """Render an answer key JSON to PDF bytes.

        Args:
            answer_key_json: The compiled answer key data
            template_name: Name of the Jinja2 template file

        Returns:
            PDF as bytes
        """
        logger.info("Rendering answer key for job: %s", answer_key_json.get("job_id"))

        try:
            from weasyprint import HTML

            template = self.jinja_env.get_template(template_name)
            html_content = template.render(
                answer_key=answer_key_json,
                rendered_at=datetime.now(timezone.utc),
            )

            pdf_bytes = HTML(string=html_content).write_pdf()
            logger.info("Answer key PDF rendered successfully")
            return pdf_bytes

        except ImportError:
            logger.warning("WeasyPrint not available, returning placeholder")
            return b"ANSWER_KEY_PLACEHOLDER"

    def get_template_path(self, template_name: str) -> Path:
        """Get the path to a template file."""
        return self.templates_dir / template_name