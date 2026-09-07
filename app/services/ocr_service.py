"""OCR Service — extracts text from image-only / scanned PDFs.

Supports:
- PaddleOCR  (primary)  — best accuracy, handles Indian fonts, 80+ languages
- Tesseract (fallback) — widely compatible, fast

The PDF is first rendered to images (via PyMuPDF or pdf2image), then OCR is
applied. Results include bounding boxes so headings can be detected by position.
"""

import io
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

# ─── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class OCRResult:
    """Result of OCR on a single page."""
    page_num: int
    text: str
    lines: list["OCRLine"] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class OCRLine:
    """A single line detected by OCR."""
    text: str
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2
    confidence: float = 0.0
    is_heading: bool = False
    heading_level: int = 0  # 0=normal, 1=h1, 2=h2, 3=h3


@dataclass
class OCRDocument:
    """Full document OCR result."""
    page_count: int
    pages: list[OCRResult] = field(default_factory=list)
    full_text: str = ""
    engine: str = "unknown"


# ─── OCR engines ────────────────────────────────────────────────────────────────

class BaseOCREngine:
    """Base class for OCR engines."""

    name: str = "base"

    def recognize(self, image_bytes: bytes, page_num: int) -> OCRResult:
        raise NotImplementedError


class PaddleOCREngine(BaseOCREngine):
    """PaddleOCR engine — best accuracy for textbooks.

    Handles:
    - Curved text, multi-angle
    - Indian fonts (Devanagari, Roman)
    - Mixed language
    - Table structures
    """

    name = "paddleocr"

    def __init__(self) -> None:
        from paddleocr import PaddleOCR as _PO

        # PaddleOCR v3.x completely revamped the API. The v2 args
        # (`show_log`, `use_angle_cls`, `use_gpu`, `cls=True`) are gone.
        # v3 uses `use_doc_orientation_classify`, `use_textline_orientation`,
        # etc. and `engine.predict(img)` instead of `engine.ocr(img, cls=True)`.
        # GPU configuration is now done via the `device` argument (e.g. "cpu",
        # "gpu", "gpu:0"); we leave it as the PaddleX default (CPU).
        self._engine = _PO(
            lang="en",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
        logger.info("PaddleOCR initialized (CPU mode, v3.x API)")

    def recognize(self, image_bytes: bytes, page_num: int) -> OCRResult:
        import cv2
        import numpy as np

        # Decode image
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return OCRResult(page_num=page_num, text="", lines=[], confidence=0.0)

        # Run OCR — PaddleOCR v3 uses predict(); v2 used ocr(cls=True).
        # Try v3 first, fall back to v2 if the engine is a v2 instance.
        try:
            result = list(self._engine.predict(img))
        except (TypeError, AttributeError):
            try:
                result = self._engine.ocr(img, cls=True)
            except Exception as e:
                logger.error("PaddleOCR call failed: %s", e)
                return OCRResult(page_num=page_num, text="", lines=[], confidence=0.0)

        lines: list[OCRLine] = []
        total_conf = 0.0
        count = 0

        # Parse v3 result: list of dicts with keys
        # rec_texts, rec_scores, rec_polys (or det_polys), etc.
        # Parse v2 result: list of [box, (text, conf)] per page.
        for page_result in result:
            texts, scores, boxes = self._extract_v3_or_v2(page_result)

            if texts is None:
                # v2 result: outer list is per-page, inner is per-line
                if isinstance(page_result, list) and page_result and isinstance(page_result[0], list):
                    for item in page_result:
                        try:
                            box = item[0]
                            text = item[1][0]
                            conf = float(item[1][1])
                        except Exception:
                            continue
                        xs = [p[0] for p in box]
                        ys = [p[1] for p in box]
                        bbox = (min(xs), min(ys), max(xs), max(ys))
                        is_heading, level = self._detect_heading(text, bbox, img.shape)
                        lines.append(OCRLine(
                            text=text.strip(),
                            bbox=bbox,
                            confidence=conf,
                            is_heading=is_heading,
                            heading_level=level,
                        ))
                        total_conf += conf
                        count += 1
                continue

            # v3 dict-like result
            for text, conf, box in zip(texts, scores, boxes):
                if not text:
                    continue
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
                bbox = (min(xs), min(ys), max(xs), max(ys))
                is_heading, level = self._detect_heading(text, bbox, img.shape)
                lines.append(OCRLine(
                    text=str(text).strip(),
                    bbox=bbox,
                    confidence=float(conf),
                    is_heading=is_heading,
                    heading_level=level,
                ))
                total_conf += float(conf)
                count += 1

        avg_conf = total_conf / count if count > 0 else 0.0
        full_text = " ".join(l.text for l in lines if l.text)

        return OCRResult(
            page_num=page_num,
            text=full_text,
            lines=lines,
            confidence=avg_conf,
        )

    @staticmethod
    def _extract_v3_or_v2(page_result) -> tuple[Optional[list], Optional[list], Optional[list]]:
        """Extract (texts, scores, boxes) from a v3 dict-like page result.

        Returns (None, None, None) if the result is v2-shaped.
        """
        if not isinstance(page_result, dict):
            return None, None, None

        # v3 keys: rec_texts, rec_scores, rec_polys (or det_polys, rec_boxes)
        texts = page_result.get("rec_texts")
        scores = page_result.get("rec_scores")
        boxes = (
            page_result.get("rec_polys")
            or page_result.get("det_polys")
            or page_result.get("rec_boxes")
        )
        if texts is None or scores is None or boxes is None:
            return None, None, None
        return list(texts), list(scores), list(boxes)

    @staticmethod
    def _detect_heading(
        text: str,
        bbox: tuple[float, float, float, float],
        img_shape: tuple[int, int, int],
    ) -> tuple[bool, int]:
        """Heuristic heading detection based on position and text features."""
        x1, y1, x2, y2 = bbox
        img_h, img_w = img_shape[:2]

        text_stripped = text.strip()
        if not text_stripped:
            return False, 0

        # Score for being a heading
        score = 0

        # 1. Position: top 15% of page = likely heading
        if y1 / img_h < 0.15:
            score += 3
        elif y1 / img_h < 0.25:
            score += 1

        # 2. Short text (headings are usually short)
        if 1 <= len(text_stripped) <= 60:
            score += 1

        # 3. All uppercase (for English headings)
        if text_stripped.isupper() and len(text_stripped) > 2:
            score += 2

        # 4. Has common heading keywords
        heading_keywords = [
            "chapter", "lesson", "topic", "section", "unit",
            "part", "module", "introduction", "summary", "exercise",
            "key points", "review", "activity",
        ]
        if any(kw in text_stripped.lower() for kw in heading_keywords):
            score += 2

        # 5. Large font estimate: wide bbox height relative to page
        box_height = y2 - y1
        if box_height / img_h > 0.03:
            score += 2

        # Thresholds
        if score >= 4:
            # Check sub-level
            if y1 / img_h < 0.05:
                return True, 1   # H1
            elif score >= 6:
                return True, 2  # H2
            return True, 3
        return False, 0


class TesseractEngine(BaseOCREngine):
    """Tesseract OCR engine — fallback when PaddleOCR fails.

    Requires system `tesseract` binary and language data.
    """

    name = "tesseract"

    def __init__(self) -> None:
        import pytesseract
        from pytesseract import pytesseract

        # Configure tesseract path
        tesseract_cmd = pytesseract.tesseract_cmd
        logger.info(f"Tesseract using: {tesseract_cmd}")

        self._pytesseract = pytesseract

    def recognize(self, image_bytes: bytes, page_num: int) -> OCRResult:
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes))
        img_w, img_h = img.size

        # Get OCR data with bounding boxes
        data = self._pytesseract.image_to_data(
            img, output_type=self._pytesseract.Output.DICT
        )

        lines_dict: dict[int, list] = {}
        for i in range(len(data["text"])):
            text = data["text"][i].strip()
            conf = float(data["conf"][i])

            if not text or conf < 30:
                continue

            block_num = data["block_num"][i]
            if block_num not in lines_dict:
                lines_dict[block_num] = []
            lines_dict[block_num].append({
                "text": text,
                "left": data["left"][i],
                "top": data["top"][i],
                "width": data["width"][i],
                "height": data["height"][i],
                "conf": conf,
            })

        lines = []
        for block_num, items in sorted(lines_dict.items()):
            # Join words on the same line (similar top)
            line_groups: dict[int, list] = {}
            for item in items:
                top = item["top"]
                if top not in line_groups:
                    line_groups[top] = []
                line_groups[top].append(item)

            for top, group in sorted(line_groups.items()):
                full_text = " ".join(it["text"] for it in group)
                left = min(it["left"] for it in group)
                right = max(it["left"] + it["width"] for it in group)
                height = group[0]["height"]
                avg_conf = sum(it["conf"] for it in group) / len(group)

                is_heading, level = TesseractEngine._detect_heading(
                    full_text, (left, top, right, top + height), (img_h, img_w)
                )

                lines.append(OCRLine(
                    text=full_text,
                    bbox=(left, top, right, top + height),
                    confidence=avg_conf,
                    is_heading=is_heading,
                    heading_level=level,
                ))

        full_text = " ".join(l.text for l in lines)
        avg_conf = sum(l.confidence for l in lines) / len(lines) if lines else 0.0

        return OCRResult(
            page_num=page_num,
            text=full_text,
            lines=lines,
            confidence=avg_conf,
        )

    @staticmethod
    def _detect_heading(
        text: str,
        bbox: tuple[float, float, float, float],
        img_shape: tuple[int, int],
    ) -> tuple[bool, int]:
        """Heuristic heading detection."""
        x1, y1, x2, y2 = bbox
        img_h, img_w = img_shape
        text_stripped = text.strip()

        if not text_stripped:
            return False, 0

        score = 0
        if y1 / img_h < 0.15:
            score += 3
        if 1 <= len(text_stripped) <= 60:
            score += 1
        if text_stripped.isupper() and len(text_stripped) > 2:
            score += 2

        heading_keywords = [
            "chapter", "lesson", "topic", "section", "unit",
            "part", "module", "introduction", "summary", "exercise",
        ]
        if any(kw in text_stripped.lower() for kw in heading_keywords):
            score += 2

        if score >= 4:
            if y1 / img_h < 0.05:
                return True, 1
            return True, 2 if score >= 6 else 3
        return False, 0


# ─── Main OCR Service ───────────────────────────────────────────────────────────

class OCRService:
    """Unified OCR service — tries PaddleOCR first, falls back to Tesseract.

    Usage:
        ocr = OCRService()
        result = await ocr.recognize_pdf("path/to/file.pdf", start_page=1, end_page=10)
    """

    def __init__(self) -> None:
        self._paddle: Optional[PaddleOCREngine] = None
        self._tesseract: Optional[TesseractEngine] = None
        self._engine_used: str = "unknown"

    def _get_paddle(self) -> Optional[PaddleOCREngine]:
        if self._paddle is None:
            try:
                self._paddle = PaddleOCREngine()
                self._engine_used = "paddleocr"
            except Exception as e:
                logger.warning("PaddleOCR init failed: %s", e)
        return self._paddle

    def _get_tesseract(self) -> Optional[TesseractEngine]:
        if self._tesseract is None:
            try:
                self._tesseract = TesseractEngine()
                self._engine_used = "tesseract"
            except Exception as e:
                logger.warning("Tesseract init failed: %s", e)
        return self._tesseract

    async def recognize_pdf(
        self,
        pdf_path: str | Path,
        start_page: int = 1,
        end_page: Optional[int] = None,
        dpi: int = 200,
    ) -> OCRDocument:
        """OCR all pages (or a range) of a PDF.

        Args:
            pdf_path: Path to the PDF file
            start_page: 1-indexed first page to process
            end_page: 1-indexed last page (None = all pages)
            dpi: Resolution for rendering (higher = better OCR, slower)

        Returns:
            OCRDocument with per-page results and full text
        """
        pdf_path = Path(pdf_path)
        logger.info(
            "Starting OCR on %s (pages %d–%s) at %d DPI",
            pdf_path.name, start_page,
            str(end_page) if end_page else "end", dpi
        )

        # Render PDF pages to images
        page_images = await self._render_pdf_to_images(pdf_path, start_page, end_page, dpi)

        if not page_images:
            logger.error("No pages rendered from PDF %s", pdf_path)
            return OCRDocument(page_count=0, engine=self._engine_used)

        # Pick the best available engine
        engine = self._get_paddle() or self._get_tesseract()
        if engine is None:
            logger.error("No OCR engine available")
            return OCRDocument(page_count=0, engine="none")

        # OCR each page
        results: list[OCRResult] = []
        total_time = 0.0

        for page_num, image_bytes in page_images:
            t0 = time.time()
            try:
                result = engine.recognize(image_bytes, page_num)
                results.append(result)
                elapsed = time.time() - t0
                total_time += elapsed
                logger.debug(
                    "Page %d: %.1fs, %d lines, conf=%.1f%%",
                    page_num, elapsed, len(result.lines), result.confidence * 100
                )
            except Exception as e:
                logger.error("OCR failed for page %d: %s", page_num, e)
                results.append(OCRResult(page_num=page_num, text="", lines=[]))

        full_text = "\n".join(r.text for r in results if r.text)
        avg_conf = sum(r.confidence for r in results) / len(results) if results else 0.0

        logger.info(
            "OCR complete: %d pages, %.1fs total, avg conf=%.1f%%, engine=%s",
            len(results), total_time, avg_conf * 100, engine.name
        )

        return OCRDocument(
            page_count=len(results),
            pages=results,
            full_text=full_text,
            engine=engine.name,
        )

    async def _render_pdf_to_images(
        self,
        pdf_path: Path,
        start_page: int,
        end_page: Optional[int],
        dpi: int,
    ) -> list[tuple[int, bytes]]:
        """Render PDF pages to PNG image bytes.

        Tries PyMuPDF first (faster), falls back to pdf2image.
        """
        try:
            return await self._render_with_pymupdf(pdf_path, start_page, end_page, dpi)
        except Exception as e:
            logger.warning("PyMuPDF render failed (%s), trying pdf2image", e)
            try:
                return await self._render_with_pdf2image(pdf_path, start_page, end_page, dpi)
            except Exception as e2:
                logger.error("pdf2image render also failed: %s", e2)
                return []

    async def _render_with_pymupdf(
        self,
        pdf_path: Path,
        start_page: int,
        end_page: Optional[int],
        dpi: int,
    ) -> list[tuple[int, bytes]]:
        """Render using PyMuPDF (fitz)."""
        import fitz  # PyMuPDF

        doc = fitz.open(str(pdf_path))
        max_page = min(end_page, len(doc)) if end_page else len(doc)
        results: list[tuple[int, bytes]] = []

        for i in range(start_page - 1, max_page):
            page = doc[i]
            # Render at specified DPI
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pix = page.get_pixmap(matrix=mat)

            # Convert to PNG bytes
            img_bytes = pix.tobytes("png")
            results.append((i + 1, img_bytes))

            # Progress log every 10 pages
            if (i - start_page + 1) % 10 == 0:
                logger.info("Rendered %d/%d pages", i - start_page + 1, max_page - start_page + 1)

        doc.close()
        return results

    async def _render_with_pdf2image(
        self,
        pdf_path: Path,
        start_page: int,
        end_page: Optional[int],
        dpi: int,
    ) -> list[tuple[int, bytes]]:
        """Render using pdf2image + PIL."""
        from pdf2image import convert_from_path

        # convert_from_path returns list of PIL Images
        images = convert_from_path(
            str(pdf_path),
            first_page=start_page,
            last_page=end_page,
            dpi=dpi,
            fmt="png",
        )

        results: list[tuple[int, bytes]] = []
        for i, img in enumerate(images):
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            results.append((start_page + i, buf.getvalue()))

        return results

    async def recognize_single_page(
        self,
        image_path: str | Path | bytes,
    ) -> OCRResult:
        """OCR a single image file or raw bytes."""
        engine = self._get_paddle() or self._get_tesseract()
        if engine is None:
            raise RuntimeError("No OCR engine available")

        if isinstance(image_path, (str, Path)):
            with open(image_path, "rb") as f:
                image_bytes = f.read()
        else:
            image_bytes = image_path

        return engine.recognize(image_bytes, page_num=0)

    def close(self) -> None:
        self._paddle = None
        self._tesseract = None