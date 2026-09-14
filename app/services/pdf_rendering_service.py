"""PDF Rendering Service — converts Question Paper and Answer Key JSON to print-ready PDFs.

Based on SDD Section 5.2.4:
- Renders Question Paper JSON and Answer Key JSON through templated HTML-to-PDF service
- Institution-configurable templates (header/logo, instructions, footer)
- Produces two separate, print-ready PDF files
"""

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import jinja2
from fpdf import FPDF

from app.core.config import settings

logger = logging.getLogger(__name__)


class PDFRenderingService:
    """Renders question papers and answer keys to PDF."""

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

    def _html_to_pdf_bytes(self, html_content: str, data: dict) -> bytes:
        """Convert HTML content to PDF bytes using FPDF (fallback).

        Produces a professionally formatted academic paper following the template pattern.
        """
        pdf = FPDF()
        pdf.add_page()

        # Extract metadata for footer
        is_paper = "title" in data
        marks = str(data.get("total_marks", "N/A")) if is_paper else "N/A"

        # --- Pre-processing: Aggressive Clean HTML ---
        html_content = re.sub(r'<style.*?>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        html_content = re.sub(r'<script.*?>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        html_content = re.sub(r'<(meta|link|title).*?>', '', html_content, flags=re.IGNORECASE)

        # --- Body Section ---
        text_content = re.sub(r'<[^<]+?>', '', html_content)
        text_content = text_content.replace('&nbsp;', ' ').replace('&amp;', '&')

        lines = text_content.split('\n')
        pdf.set_font("Arial", '', 12)

        for line in lines:
            stripped_line = line.strip()
            if not stripped_line:
                continue

            if "SECTION" in stripped_line.upper() and ("-" in stripped_line or "–" in stripped_line):
                pdf.ln(10)
                pdf.set_font("Arial", 'B', 14)
                pdf.cell(0, 10, stripped_line.upper(), ln=True, align='L')
                pdf.set_font("Arial", '', 12)
            elif "Marks" in stripped_line and "x" in stripped_line:
                pdf.set_font("Arial", 'B', 11)
                pdf.cell(0, 10, stripped_line, ln=True, align='L')
                pdf.set_font("Arial", '', 12)
            elif re.match(r'^(\d+|Q\d+)\.', stripped_line):
                pdf.ln(5)
                pdf.set_font("Arial", 'B', 12)
                pdf.set_x(15)
                pdf.multi_cell(180, 10, txt=stripped_line)
                pdf.set_font("Arial", '', 12)
            else:
                pdf.set_x(20)
                pdf.multi_cell(170, 8, txt=stripped_line)

        # Footer
        pdf.set_y(-30)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, "TOTAL: " + marks + " MARKS", ln=True, align='C')
        pdf.cell(0, 10, "ALL THE BEST", ln=True, align='C')
        pdf.ln(10)
        pdf.cell(0, 10, "Teacher's Signature: ______________________", ln=True, align='R')

        return pdf.output()

    async def render_question_paper(
        self,
        paper_json: dict,
        template_name: str = "question_paper.html",
    ) -> bytes:
        """Render a question paper JSON to PDF bytes."""
        logger.info("Rendering question paper: %s", paper_json.get("title"))

        try:
            from weasyprint import HTML

            template = self.jinja_env.get_template(template_name)
            html_content = template.render(
                paper=paper_json,
                rendered_at=datetime.now(timezone.utc),
            )
            pdf_bytes = HTML(string=html_content).write_pdf()
            logger.info("Question paper PDF rendered successfully with WeasyPrint")
            return pdf_bytes

        except (ImportError, OSError, RuntimeError) as e:
            logger.warning("WeasyPrint not available or failed (%s), falling back to FPDF", e)
            template = self.jinja_env.get_template(template_name)
            html_content = template.render(
                paper=paper_json,
                rendered_at=datetime.now(timezone.utc),
            )
            pdf_bytes = self._html_to_pdf_bytes(html_content, paper_json)
            logger.info("Question paper PDF rendered with FPDF fallback")
            return pdf_bytes

    async def render_answer_key(
        self,
        answer_key_json: dict,
        template_name: str = "answer_key.html",
    ) -> bytes:
        """Render an answer key JSON to PDF bytes."""
        logger.info("Rendering answer key for job: %s", answer_key_json.get("job_id"))

        try:
            from weasyprint import HTML

            template = self.jinja_env.get_template(template_name)
            html_content = template.render(
                answer_key=answer_key_json,
                rendered_at=datetime.now(timezone.utc),
            )
            pdf_bytes = HTML(string=html_content).write_pdf()
            logger.info("Answer key PDF rendered successfully with WeasyPrint")
            return pdf_bytes

        except (ImportError, OSError, RuntimeError) as e:
            logger.warning("WeasyPrint not available or failed (%s), falling back to FPDF", e)
            template = self.jinja_env.get_template(template_name)
            html_content = template.render(
                answer_key=answer_key_json,
                rendered_at=datetime.now(timezone.utc),
            )
            pdf_bytes = self._html_to_pdf_bytes(html_content, answer_key_json)
            logger.info("Answer key PDF rendered with FPDF fallback")
            return pdf_bytes

    def get_template_path(self, template_name: str) -> Path:
        """Get the path to a template file."""
        return self.templates_dir / template_name
