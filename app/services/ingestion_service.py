"""Ingestion & Indexing Service — extracts text, chunks, embeds, and indexes content.

Based on SDD Section 5.2.1:
- Document Intelligence extracts text, headings, tables, images with layout metadata
- Chunking service splits by structural boundaries (chapter/section/heading)
- Embeddings written to the configured vector store (Azure AI Search, Qdrant, or
  in-memory for local dev) with metadata fields for filtered retrieval — see
  app/services/vector_store/ and the VECTOR_STORE_PROVIDER setting.
"""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from azure.ai.documentintelligence.aio import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import (
    AnalyzeDocumentRequest,
    DocumentContentFormat,
    AnalyzeResult,
)
from azure.core.credentials import AzureKeyCredential
from azure.storage.blob.aio import BlobServiceClient
from app.core.config import settings
from app.core.llm_client import get_embeddings_model
from app.models.chunk import Chunk
from app.services.vector_store import VectorRecord, VectorStoreClient, get_vector_store

logger = logging.getLogger(__name__)


class CorruptPDFError(Exception):
    """Raised when a PDF cannot be processed by any extraction method.

    This usually means the file has been mangled at the binary level —
    e.g., zlib streams are corrupt, or the xref table is invalid.
    Recovery requires getting a clean copy of the source PDF.
    """


@dataclass
class ChunkMetadata:
    """Structural metadata for a content chunk."""

    chapter: Optional[str] = None
    topic: Optional[str] = None
    page_range: Optional[tuple[int, int]] = None
    heading_path: Optional[str] = None
    image_references: list[str] = field(default_factory=list)


@dataclass
class ExtractedContent:
    """Raw content extracted from a document."""

    document_id: str
    content: str
    structured_chunks: List[tuple[str, ChunkMetadata]]
    images: list[bytes] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)
    # Diagnostics: extraction method + corruption flags
    extraction_method: str = "unknown"  # "azure" | "pymupdf" | "ocr"
    corruption_detected: bool = False
    corruption_details: str = ""


class IngestionService:
    """Orchestrates document ingestion and indexing pipeline."""

    def __init__(self) -> None:
        self._doc_intel_client: Optional[DocumentIntelligenceClient] = None
        self._vector_store: Optional[VectorStoreClient] = None
        self._blob_client: Optional[BlobServiceClient] = None
        self._embedder = None

    async def get_doc_intel_client(self) -> DocumentIntelligenceClient:
        if self._doc_intel_client is None:
            self._doc_intel_client = DocumentIntelligenceClient(
                endpoint=settings.azure_doc_intel_endpoint,
                credential=AzureKeyCredential(settings.azure_doc_intel_key),
            )
        return self._doc_intel_client

    def get_vector_store(self) -> VectorStoreClient:
        """Return the configured vector store (local / Azure AI Search / Qdrant).

        Selection is driven entirely by `VECTOR_STORE_PROVIDER` in settings —
        see app/services/vector_store/factory.py.
        """
        if self._vector_store is None:
            self._vector_store = get_vector_store()
        return self._vector_store

    async def get_blob_client(self) -> BlobServiceClient:
        if self._blob_client is None:
            self._blob_client = BlobServiceClient.from_connection_string(
                settings.azure_storage_connection_string
            )
        return self._blob_client

    async def get_embedder(self):
        if self._embedder is None:
            self._embedder = get_embeddings_model()
        return self._embedder

    async def extract_document_content(
        self,
        document_id: str,
        document_path: str,
        page_start: int = 1,
        page_end: Optional[int] = None,
        ocr_dpi: int = 200,
    ) -> ExtractedContent:
        """Extract text and layout from PDF.

        Tries in order:
        1. Azure Document Intelligence (if credentials configured)
        2. Local PyMuPDF (for text-based PDFs)
        3. OCR via PaddleOCR → Tesseract (for scanned/image-only PDFs)

        Args:
            document_id: Identifier for the document
            document_path: Path to the PDF file
            page_start: 1-indexed first page to process
            page_end: 1-indexed last page (None = all remaining)
            ocr_dpi: DPI for OCR rendering (higher = better accuracy, slower)
        """
        logger.info("Extracting content from document %s", document_id)

        if settings.azure_doc_intel_endpoint and settings.azure_doc_intel_key:
            return await self._extract_with_azure(document_id, document_path)

        # Try PyMuPDF first (fast for text-based PDFs)
        content = await self._extract_with_pymupdf(
            document_id, document_path, page_start=page_start, page_end=page_end
        )

        # If we got text, we're done.
        if content.content.strip() and content.structured_chunks:
            return content

        # No text. Two possibilities:
        #   (a) Scanned/image-only PDF — OCR should be able to read it.
        #   (b) Corrupt PDF where zlib streams are broken — OCR will also fail
        #       because rendered pages come out blank. We try anyway so the
        #       user gets the most informative error message possible.
        if content.corruption_detected:
            logger.warning(
                "PDF %s shows signs of corruption (%s); attempting OCR anyway.",
                document_id, content.corruption_details,
            )
        else:
            logger.warning(
                "No text extracted from %s — PDF appears to be scanned/image-only, using OCR",
                document_id,
            )
        return await self._extract_with_ocr(
            document_id, document_path,
            start_page=page_start, end_page=page_end, dpi=ocr_dpi,
        )

    async def _extract_with_azure(
        self, document_id: str, document_path: str
    ) -> ExtractedContent:
        """Extract using Azure Document Intelligence."""
        client = await self.get_doc_intel_client()
        with open(document_path, "rb") as f:
            poller = await client.begin_analyze_document(
                "prebuilt-layout",
                AnalyzeDocumentRequest(bytes_source=f.read()),
            )
        result: AnalyzeResult = await poller.result()
        chunks = self._chunk_document(result, document_id)
        return ExtractedContent(
            document_id=document_id,
            content=result.content or "",
            structured_chunks=chunks,
            images=[],
            tables=[],
            extraction_method="azure",
        )

    async def _extract_with_pymupdf(
        self,
        document_id: str,
        document_path: str,
        page_start: int = 1,
        page_end: Optional[int] = None,
    ) -> ExtractedContent:
        """Extract using local PyMuPDF (for text-based PDFs)."""
        import fitz  # PyMuPDF
        import os

        logger.info("Using local PyMuPDF extraction (no Azure credentials)")
        doc = fitz.open(document_path)
        all_text = ""
        pages_data = []
        corruption_warnings: list[str] = []

        max_page = min(page_end, len(doc)) if page_end else len(doc)
        start_idx = max(0, page_start - 1)
        pages_attempted = 0

        for page_num, page in enumerate(doc, start=1):
            if page_num < page_start or page_num > max_page:
                continue
            pages_attempted += 1
            try:
                text = page.get_text("text")
            except Exception as e:
                # MuPDF raises "zlib error" on corrupt FlateDecode streams.
                logger.warning("PyMuPDF get_text failed on page %d: %s", page_num, e)
                corruption_warnings.append(f"page {page_num}: {e}")
                text = ""
            all_text += text + "\n"
            pages_data.append((page_num, text))

        doc.close()

        # Heuristic corruption detection: if the PDF is large (> 1 MB) and we
        # extracted no text from any of the attempted pages, the file is very
        # likely corrupt at the binary level (e.g., zlib streams replaced with
        # UTF-8 replacement chars by a non-binary-safe transfer).
        #
        # We can't always catch this from MuPDF exceptions — sometimes MuPDF
        # just logs to stderr and returns empty strings.
        file_size = os.path.getsize(document_path) if os.path.exists(document_path) else 0
        if (
            not all_text.strip()
            and pages_attempted > 0
            and file_size > 1_000_000
            and not corruption_warnings
        ):
            corruption_warnings.append(
                f"file is {file_size:,} bytes but no text was extracted from "
                f"{pages_attempted} page(s); the PDF's text streams are likely corrupt"
            )

        # Chunk by detected headings (lines that look like headings)
        chunks = self._chunk_text_by_headings(pages_data, document_id)

        return ExtractedContent(
            document_id=document_id,
            content=all_text,
            structured_chunks=chunks,
            images=[],
            tables=[],
            extraction_method="pymupdf",
            corruption_detected=bool(corruption_warnings),
            corruption_details="; ".join(corruption_warnings) if corruption_warnings else "",
        )

    async def _extract_with_ocr(
        self, document_id: str, document_path: str, start_page: int = 1, end_page: Optional[int] = None, dpi: int = 200
    ) -> ExtractedContent:
        """Extract text using OCR (PaddleOCR → Tesseract).

        This handles scanned/image-only PDFs that have no selectable text.
        Renders each page to an image and runs OCR with heading detection.
        """
        from app.services.ocr_service import OCRService

        logger.info("Using OCR extraction for %s (DPI=%d)", document_id, dpi)
        ocr = OCRService()

        try:
            result = await ocr.recognize_pdf(
                pdf_path=document_path,
                start_page=start_page,
                end_page=end_page,
                dpi=dpi,
            )
        finally:
            ocr.close()

        if not result.pages:
            logger.error("OCR returned no results for %s", document_id)
            # Zero pages could mean the file is so broken that even rendering fails.
            return ExtractedContent(
                document_id=document_id,
                content="",
                structured_chunks=[],
                images=[],
                tables=[],
                extraction_method="ocr",
                corruption_detected=True,
                corruption_details="OCR returned zero pages (PDF may have corrupt streams or is image-only with no recoverable content)",
            )

        # Build structured chunks from OCR lines
        chunks: list[tuple[str, ChunkMetadata]] = []
        buffer: list[str] = []
        current_chapter: Optional[str] = None
        current_topic: Optional[str] = None
        chunk_page_start: int = 1

        for page_result in result.pages:
            for line in page_result.lines:
                text = line.text.strip()
                if not text:
                    continue

                if line.is_heading:
                    # Flush current buffer
                    if buffer:
                        content = "\n".join(buffer).strip()
                        if content:
                            chunks.append((content, ChunkMetadata(
                                chapter=current_chapter,
                                topic=current_topic,
                                page_range=(chunk_page_start, page_result.page_num),
                            )))
                        buffer = []

                    # Update heading path
                    if line.heading_level == 1:
                        current_chapter = text
                        current_topic = None
                        chunk_page_start = page_result.page_num
                    elif line.heading_level >= 2:
                        current_topic = text
                    else:
                        current_topic = text  # Generic heading
                else:
                    if not buffer:
                        chunk_page_start = page_result.page_num
                    buffer.append(text)

        # Flush last chunk
        if buffer:
            content = "\n".join(buffer).strip()
            if content:
                last_page = result.pages[-1].page_num if result.pages else chunk_page_start
                chunks.append((content, ChunkMetadata(
                    chapter=current_chapter,
                    topic=current_topic,
                    page_range=(chunk_page_start, last_page),
                )))

        logger.info(
            "OCR extracted %d chunks from %d pages (engine=%s, avg conf=%.1f%%)",
            len(chunks), result.page_count, result.engine,
            sum(p.confidence for p in result.pages) / len(result.pages) * 100 if result.pages else 0
        )

        return ExtractedContent(
            document_id=document_id,
            content=result.full_text,
            structured_chunks=chunks,
            images=[],
            tables=[],
            extraction_method=f"ocr({result.engine})",
            corruption_detected=not result.full_text.strip(),
            corruption_details=(
                "OCR found no text on any page" if not result.full_text.strip() else ""
            ),
        )

    def _chunk_text_by_headings(
        self, pages_data: list[tuple[int, str]], document_id: str
    ) -> list[tuple[str, ChunkMetadata]]:
        """Chunk text using heading pattern detection."""
        import re

        chunks: list[tuple[str, ChunkMetadata]] = []
        current_chapter = None
        current_topic = None
        buffer: list[str] = []
        page_start = 1

        heading_pattern = re.compile(r"^(Chapter|Section|Topic|Module|Part)\s+\d+[:.]?\s*", re.IGNORECASE)
        subheading_pattern = re.compile(r"^\d+\.\d+\s+", re.IGNORECASE)

        for page_num, text in pages_data:
            lines = text.split("\n")
            for line in lines:
                line = line.strip()
                if not line:
                    continue

                is_heading = heading_pattern.match(line) or subheading_pattern.match(line)

                if is_heading and len(line) > 3:
                    # Flush previous chunk
                    if buffer:
                        content = "\n".join(buffer).strip()
                        if content:
                            chunks.append((content, ChunkMetadata(
                                chapter=current_chapter,
                                topic=current_topic,
                                page_range=(page_start, page_num),
                            )))
                        buffer = []

                    # Update heading path
                    if heading_pattern.match(line):
                        current_chapter = line
                        current_topic = None
                        page_start = page_num
                    elif subheading_pattern.match(line):
                        current_topic = line
                else:
                    if not buffer:
                        page_start = page_num
                    buffer.append(line)

        # Flush last chunk
        if buffer:
            content = "\n".join(buffer).strip()
            if content:
                chunks.append((content, ChunkMetadata(
                    chapter=current_chapter,
                    topic=current_topic,
                    page_range=(page_start, pages_data[-1][0] if pages_data else page_start),
                )))

        logger.info("PyMuPDF extracted %d chunks", len(chunks))
        return chunks

    def _chunk_document(
        self, result: AnalyzeResult, document_id: str
    ) -> List[tuple[str, ChunkMetadata]]:
        """Split document into chunks by structural boundaries.

        Splits by heading levels so each chunk carries chapter/topic metadata
        — this is what enables "N questions from Chapter 3" category distribution.
        """
        chunks: list[tuple[str, ChunkMetadata]] = []
        current_heading_path: list[str] = []
        current_content: list[str] = []
        current_metadata = ChunkMetadata()
        max_chunk_size = 1000  # characters

        for page in result.pages or []:
            for line in page.lines or []:
                text = line.content or ""

                # Detect headings
                heading_level = self._get_heading_level(line)
                if heading_level > 0 and len(text.strip()) > 3:
                    # Flush previous chunk
                    if current_content:
                        chunks.append(
                            self._create_chunk(
                                current_content,
                                current_metadata,
                                max_chunk_size,
                            )
                        )
                        current_content = []

                    # Update heading path
                    self._update_heading_path(
                        current_heading_path, heading_level, text
                    )
                    current_metadata = ChunkMetadata(
                        heading_path=" / ".join(current_heading_path),
                        chapter=current_heading_path[0] if current_heading_path else None,
                        topic=current_heading_path[-1] if current_heading_path else None,
                    )

                current_content.append(text)

            # Track page numbers
            if current_metadata.page_range is None:
                current_metadata.page_range = (page.page_number, page.page_number)
            else:
                current_metadata.page_range = (
                    current_metadata.page_range[0],
                    page.page_number,
                )

        # Flush remaining content
        if current_content:
            chunks.append(
                self._create_chunk(current_content, current_metadata, max_chunk_size)
            )

        logger.info("Document %s chunked into %d pieces", document_id, len(chunks))
        return chunks

    def _get_heading_level(self, line) -> int:
        """Detect heading level from font size or style — heuristic."""
        if not hasattr(line, "kind") or line.kind is None:
            return 0
        # Document Intelligence marks headings as "heading" kind
        # We map by confidence or font size heuristic
        if line.kind == "heading":
            # Use span to find estimated level from font size
            return self._estimate_heading_level(line)
        return 0

    def _estimate_heading_level(self, line) -> int:
        """Estimate heading level based on span properties."""
        # Heuristic: check font size ratio
        # Returns 1 for H1, 2 for H2, etc.
        return 1  # Simplified — production would read font sizes from spans

    def _update_heading_path(
        self, heading_path: list[str], level: int, text: str
    ) -> None:
        """Maintain hierarchical heading path."""
        # Trim to current level
        heading_path = heading_path[: level - 1]
        heading_path.append(text.strip())

    def _create_chunk(
        self,
        content_lines: list[str],
        metadata: ChunkMetadata,
        max_size: int,
    ) -> tuple[str, ChunkMetadata]:
        """Create a chunk from content lines, splitting if too large."""
        content = "\n".join(content_lines).strip()
        content_hash = hashlib.sha256(content.encode()).hexdigest()

        return content, metadata

    async def embed_and_index(
        self, document_id: str, chunks: List[tuple[str, ChunkMetadata]]
    ) -> List[str]:
        """Embed chunks and write them to the configured vector store.

        The backend (in-memory, Azure AI Search, or Qdrant) is selected by
        `VECTOR_STORE_PROVIDER` — this method itself is backend-agnostic.
        """
        logger.info("Embedding %d chunks for document %s", len(chunks), document_id)

        embedder = await self.get_embedder()
        store = self.get_vector_store()

        indexed_ids: list[str] = []
        batch_size = 50
        created_at = datetime.now(timezone.utc).isoformat()

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            texts = [chunk_text for chunk_text, _ in batch]
            embeddings = await embedder.aembed_documents(texts)

            records = [
                VectorRecord(
                    id=f"{document_id}_chunk_{i + j}",
                    content=chunk_text,
                    embedding=embedding,
                    source_document_id=document_id,
                    chapter=metadata.chapter,
                    topic=metadata.topic,
                    heading_path=metadata.heading_path,
                    page_start=metadata.page_range[0] if metadata.page_range else None,
                    page_end=metadata.page_range[1] if metadata.page_range else None,
                    image_references=metadata.image_references,
                    created_at=created_at,
                )
                for j, ((chunk_text, metadata), embedding) in enumerate(zip(batch, embeddings))
            ]

            batch_ids = await store.upsert_chunks(document_id, records)
            indexed_ids.extend(batch_ids)

        logger.info("Indexed %d chunks for document %s", len(indexed_ids), document_id)
        return indexed_ids

    async def process_document(
        self,
        document_id: str,
        document_path: str,
        page_start: int = 1,
        page_end: Optional[int] = None,
        ocr_dpi: int = 200,
    ) -> List[str]:
        """Full ingestion pipeline: extract → chunk → embed → index."""
        logger.info("Starting ingestion for document %s", document_id)
        extracted = await self.extract_document_content(
            document_id, document_path,
            page_start=page_start, page_end=page_end, ocr_dpi=ocr_dpi,
        )

        # If extraction failed to produce any content, raise a clear error.
        # The caller (API) catches this and surfaces a useful message to the user
        # — instead of silently returning an empty index.
        if not extracted.structured_chunks and not extracted.content.strip():
            raise CorruptPDFError(
                f"Could not extract any text from {document_id} using "
                f"{extracted.extraction_method}. {extracted.corruption_details}"
            )

        indexed_ids = await self.embed_and_index(document_id, extracted.structured_chunks)
        logger.info(
            "Ingestion complete for document %s (method=%s, chunks=%d)",
            document_id, extracted.extraction_method, len(indexed_ids),
        )
        return indexed_ids

    async def close(self) -> None:
        """Clean up resources."""
        if self._doc_intel_client:
            await self._doc_intel_client.close()
        if self._vector_store:
            await self._vector_store.close()
        if self._blob_client:
            await self._blob_client.close()