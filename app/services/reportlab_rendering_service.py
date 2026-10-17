"""ReportLab Rendering Service — converts Question Paper and Answer Key JSON to print-ready PDFs using ReportLab.
This service replicates the exact styling from qpg_sample.py to ensure consistency.
"""

import json
import tempfile
import os
from typing import Any, Dict, List, Tuple
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Import the build function from qpg_sample
import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
from qpg_sample import ROMAN, HeaderBlock, build, fmt, header_fields, load_image, NAVY, TEAL, TEAL_L, LIGHT, AMBER, GREY, LINE, INK, FB, W

# Folder that relative logo_url / image_url values are resolved against (holds edusol_logo.jpeg)
ASSETS_DIR = str(Path(__file__).parent.parent / "static" / "images")
DEFAULT_LOGO = "edusol_logo.jpeg"


class ReportLabRenderingService:
    """Renders question papers and answer keys to PDF using ReportLab (matching qpg_sample.py styling)."""

    def __init__(self) -> None:
        """Initialize the ReportLab rendering service."""
        pass

    def _ensure_sections(self, paper_json: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure the paper JSON has sections format compatible with qpg_sample.py build()."""
        # If already has sections, return as-is
        if paper_json.get("sections"):
            return paper_json

        # If has flat questions, group them by question type
        if paper_json.get("questions"):
            secs, order = {}, []
            for q in paper_json["questions"]:
                k = q.get("question_type", "questions")
                if k not in secs:
                    secs[k] = {
                        "section_title": k.replace("_", " ").title(),
                        "instructions": "",
                        "questions": []
                    }
                    order.append(k)
                secs[k]["questions"].append(q)
            paper_json["sections"] = [secs[k] for k in order]

        return paper_json

    async def render_question_paper(
        self,
        paper_json: Dict[str, Any],
    ) -> bytes:
        """Render a question paper JSON to PDF bytes using ReportLab.

        Args:
            paper_json: The question paper JSON object (expected to have title, total_marks,
                       total_questions, sections, questions, etc.)

        Returns:
            PDF bytes matching the qpg_sample.py styling
        """
        logger.info("Rendering question paper: %s", paper_json.get("title"))

        try:
            # Create a temporary file for the input JSON
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_json:
                # Ensure sections format for compatibility
                paper_copy = self._ensure_sections(paper_json.copy())
                paper_copy.setdefault("logo_url", DEFAULT_LOGO)
                json.dump(paper_copy, temp_json, indent=2)
                temp_json_path = temp_json.name

            try:
                # Create a temporary file for the output PDF
                with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_pdf:
                    temp_pdf_path = temp_pdf.name

                try:
                    # Use the existing build function from qpg_sample.py
                    output_path, _ = build(
                        json_path=temp_json_path,
                        out_path=temp_pdf_path,
                        assets_dir=ASSETS_DIR,
                    )

                    # Read the generated PDF
                    with open(output_path, 'rb') as f:
                        pdf_bytes = f.read()

                    logger.info("Question paper PDF rendered successfully with ReportLab (%d bytes)", len(pdf_bytes))
                    return pdf_bytes

                finally:
                    # Clean up the PDF temp file
                    if os.path.exists(temp_pdf_path):
                        os.unlink(temp_pdf_path)

            finally:
                # Clean up the JSON temp file
                if os.path.exists(temp_json_path):
                    os.unlink(temp_json_path)

        except Exception as e:
            logger.error("Failed to render question paper with ReportLab: %s", e)
            raise

    @staticmethod
    def _as_text(value: Any) -> str:
        """Flatten LLM output (str / list / dict / None) into display text."""
        if value is None:
            return ""
        if isinstance(value, dict):
            return "\n".join(f"{k}: {v}" for k, v in value.items())
        if isinstance(value, (list, tuple)):
            return "\n".join(ReportLabRenderingService._as_text(v) for v in value)
        return str(value)

    @staticmethod
    def _scheme_rows(scheme: Any) -> List[Tuple[str, str]]:
        """Normalise a marking scheme (dict / list / str) into (step, marks) rows."""
        if not scheme:
            return []
        if isinstance(scheme, dict):
            return [(str(k), "" if v is None else str(v)) for k, v in scheme.items()]
        if isinstance(scheme, (list, tuple)):
            rows = []
            for item in scheme:
                if isinstance(item, dict):
                    marks = next((item[k] for k in ("marks", "mark", "points") if k in item), "")
                    step = next((item[k] for k in ("step", "point", "criteria", "description", "key_point") if k in item),
                                ", ".join(f"{k}: {v}" for k, v in item.items() if k not in ("marks", "mark", "points")))
                    rows.append((str(step), str(marks)))
                else:
                    rows.append((str(item), ""))
            return rows
        return [(str(scheme), "")]

    @staticmethod
    def _marks_label(marks: Any) -> str:
        try:
            m = float(marks)
        except (TypeError, ValueError):
            return str(marks)
        return f"{m:g} Mark" + ("" if m == 1 else "s")

    async def render_answer_key(
        self,
        answer_key_json: Dict[str, Any],
    ) -> bytes:
        """Render an answer key JSON to PDF bytes using ReportLab.

        Args:
            answer_key_json: The answer key JSON object (expected to have job_id, answers,
                           total_questions, total_marks, etc.)

        Returns:
            PDF bytes with answer key styling matching qpg_sample.py theme

        Raises:
            Exception: if rendering fails, so callers never store an empty PDF.
        """
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.lib.enums import TA_CENTER
        from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle

        logger.info("Rendering answer key for job: %s", answer_key_json.get("job_id"))

        st = {
            "qh": ParagraphStyle("qh", fontName=FB, fontSize=10, leading=13, textColor=NAVY),
            "qm": ParagraphStyle("qm", fontName=FB, fontSize=9, leading=13, textColor=TEAL, alignment=2),
            "qt": ParagraphStyle("qt", fontName="Helvetica-Oblique", fontSize=9, leading=12, textColor=GREY, leftIndent=6),
            "lbl": ParagraphStyle("lbl", fontName=FB, fontSize=8, leading=11, textColor=NAVY, leftIndent=6, spaceBefore=3),
            "txt": ParagraphStyle("txt", fontName="Helvetica", fontSize=9.5, leading=13, textColor=INK, leftIndent=6),
            "sub": ParagraphStyle("sub", fontName="Helvetica", fontSize=9.5, leading=13, textColor=INK, leftIndent=18, firstLineIndent=-12),
            "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=8.5, leading=11, textColor=INK),
            "cellb": ParagraphStyle("cellb", fontName=FB, fontSize=8.5, leading=11, textColor=NAVY),
            "end": ParagraphStyle("end", fontName=FB, fontSize=8, leading=10, textColor=GREY, alignment=TA_CENTER),
        }

        def paras(text: str, style) -> list:
            return [Paragraph(fmt(line), style) for line in text.splitlines() if line.strip()]

        job_id = answer_key_json.get("job_id", "unknown")
        meta = [("QUESTIONS", str(answer_key_json.get("total_questions", 0))),
                ("TOTAL MARKS", str(answer_key_json.get("total_marks", 0)))]
        if answer_key_json.get("negative_marking_enabled"):
            meta.append(("NEGATIVE MARKING", f"-{answer_key_json.get('negative_marks_per_wrong', 0)} / wrong"))
        logo = load_image(answer_key_json.get("logo_url") or DEFAULT_LOGO, ASSETS_DIR)

        school, exam_title, title, level = header_fields(answer_key_json)

        meta_t = Table([[[Paragraph(l, ParagraphStyle("ml", fontName="Helvetica", fontSize=7, leading=9, textColor=GREY)),
                          Paragraph(fmt(v), ParagraphStyle("mv", fontName=FB, fontSize=11, leading=14, textColor=NAVY))]
                         for l, v in meta]], colWidths=[W / len(meta)] * len(meta))
        meta_t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                                    ("LINEAFTER", (0, 0), (-2, -1), 0.6, LINE), ("TOPPADDING", (0, 0), (-1, -1), 5),
                                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
        story = [HeaderBlock(school, exam_title, title, level, logo, one_line_title=True), Spacer(1, 4 * mm), meta_t, Spacer(1, 6 * mm)]

        for idx, ans in enumerate(answer_key_json.get("answers", []), 1):
            head = Table([[Paragraph(f"Question {idx}", st["qh"]), Paragraph(self._marks_label(ans.get("marks", 0)), st["qm"])]],
                         colWidths=[W - 40 * mm, 40 * mm])
            head.setStyle(TableStyle([("LINEBEFORE", (0, 0), (0, 0), 2.5, TEAL), ("LINEBELOW", (0, 0), (-1, 0), 0.5, LINE),
                                      ("LEFTPADDING", (0, 0), (0, 0), 6), ("RIGHTPADDING", (-1, 0), (-1, 0), 0),
                                      ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
            block = [head, Spacer(1, 1.5 * mm)]
            block += paras(self._as_text(ans.get("question_text")), st["qt"])

            sub_answers = [s for s in (ans.get("sub_answers") or []) if isinstance(s, dict)]
            if sub_answers:
                block.append(Paragraph("ANSWERS", st["lbl"]))
                for i, sa in enumerate(sub_answers):
                    label = ROMAN[i] if i < len(ROMAN) else str(i + 1)
                    q_txt = fmt(self._as_text(sa.get("question_text")))
                    a_txt = fmt(self._as_text(sa.get("answer") or sa.get("answer_outline")))
                    m_txt = f" <font color='#0E7C86'>[{self._marks_label(sa.get('marks'))}]</font>" if sa.get("marks") is not None else ""
                    block.append(Paragraph(f"<b>({label})</b> <i>{q_txt}</i>{m_txt}<br/>{a_txt}", st["sub"]))
            else:
                outline = self._as_text(ans.get("answer_outline")) or self._as_text(ans.get("correct_answer"))
                if outline:
                    block.append(Paragraph("ANSWER", st["lbl"]))
                    block += paras(outline, st["txt"])
                sample = self._as_text(ans.get("sample_answer"))
                if sample and sample.strip() != outline.strip():
                    block.append(Paragraph("MODEL ANSWER", st["lbl"]))
                    block += paras(sample, st["txt"])

            rows = self._scheme_rows(ans.get("marking_scheme"))
            if rows:
                block.append(Paragraph("MARKING SCHEME", st["lbl"]))
                scheme = Table([[Paragraph(fmt(step), st["cell"]), Paragraph(fmt(m), st["cellb"])] for step, m in rows],
                               colWidths=[W - 36 * mm, 30 * mm], hAlign="RIGHT")
                scheme.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("GRID", (0, 0), (-1, -1), 0.5, LINE),
                                            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 4),
                                            ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
                block.append(scheme)
            story += block + [Spacer(1, 6 * mm)]

        story.append(Paragraph("-  End of Answer Key  -", st["end"]))

        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_pdf:
            temp_pdf_path = temp_pdf.name
        try:
            doc = BaseDocTemplate(temp_pdf_path, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=12 * mm,
                                  bottomMargin=18 * mm, title="Answer Key", author="Question Paper Generator")
            doc.addPageTemplates([PageTemplate(id="all", frames=[Frame(16 * mm, 18 * mm, A4[0] - 32 * mm, A4[1] - 30 * mm,
                                                                       leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)])])
            doc.build(story)
            with open(temp_pdf_path, 'rb') as f:
                pdf_bytes = f.read()
            logger.info("Answer key PDF rendered successfully with ReportLab (%d bytes)", len(pdf_bytes))
            return pdf_bytes
        except Exception:
            logger.exception("Failed to render answer key with ReportLab for job %s", job_id)
            raise
        finally:
            if os.path.exists(temp_pdf_path):
                os.unlink(temp_pdf_path)
