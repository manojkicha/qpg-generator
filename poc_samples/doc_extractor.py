"""
POC: Extract content from a scanned PDF using Azure AI Document Intelligence.

Model used by default: prebuilt-layout
    - Handles OCR text extraction from scanned/image-based PDFs
    - Also extracts tables, selection marks, and structural layout (headings, paragraphs)
    - If you only need raw OCR text (no tables/structure), swap to "prebuilt-read"
      which is faster and cheaper for pure text extraction.

Requirements:
    pip install azure-ai-documentintelligence azure-core python-dotenv

Environment variables expected (.env or exported):
    AZURE_DOCINTEL_ENDPOINT   -> e.g. https://<your-resource-name>.cognitiveservices.azure.com/
    AZURE_DOCINTEL_KEY        -> resource API key
"""

import json
import logging
import os
import sys
from pathlib import Path

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeResult
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

# Default model — change here if you need a different prebuilt/custom model
DEFAULT_MODEL_ID = "prebuilt-layout"


def get_client() -> DocumentIntelligenceClient:
    """Build an authenticated Document Intelligence client from env vars."""
    load_dotenv()
    endpoint = os.getenv("AZURE_DOCINTEL_ENDPOINT")
    key = os.getenv("AZURE_DOCINTEL_KEY")

    if not endpoint or not key:
        raise EnvironmentError(
            "Missing AZURE_DOCINTEL_ENDPOINT or AZURE_DOCINTEL_KEY. "
            "Set them as environment variables or in a .env file."
        )

    return DocumentIntelligenceClient(
        endpoint=endpoint,
        credential=AzureKeyCredential(key),
    )


def analyze_pdf(
    client: DocumentIntelligenceClient,
    pdf_path: Path,
    model_id: str = DEFAULT_MODEL_ID,
) -> AnalyzeResult:
    """Submit the scanned PDF to Document Intelligence and return the result."""
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    logger.info("Submitting '%s' to model '%s'", pdf_path.name, model_id)

    with open(pdf_path, "rb") as f:
        poller = client.begin_analyze_document(
            model_id=model_id,
            body=f,
            content_type="application/pdf",
        )

    logger.info("Analysis in progress... (operation id: %s)", poller.details.get("operation_id", "n/a"))
    result: AnalyzeResult = poller.result()
    logger.info("Analysis complete.")
    return result


def extract_plain_text(result: AnalyzeResult) -> str:
    """Concatenate OCR'd text across all pages, in reading order."""
    if result.content:
        return result.content
    # Fallback: rebuild from page lines if top-level content is empty
    lines = []
    for page in result.pages or []:
        for line in page.lines or []:
            lines.append(line.content)
    return "\n".join(lines)


def extract_tables(result: AnalyzeResult) -> list[dict]:
    """Extract tables as a list of simple row/column dicts."""
    tables_out = []
    for t_idx, table in enumerate(result.tables or []):
        cells = [
            {
                "row_index": cell.row_index,
                "column_index": cell.column_index,
                "content": cell.content,
            }
            for cell in table.cells
        ]
        tables_out.append(
            {
                "table_index": t_idx,
                "row_count": table.row_count,
                "column_count": table.column_count,
                "cells": cells,
            }
        )
    return tables_out


def build_summary(pdf_path: Path, model_id: str, result: AnalyzeResult) -> dict:
    """Assemble a JSON-serializable summary of the extraction."""
    return {
        "source_file": pdf_path.name,
        "model_used": model_id,
        "page_count": len(result.pages or []),
        "text": extract_plain_text(result),
        "tables": extract_tables(result),
    }


def main():
    # if len(sys.argv) < 2:
    #     print("Usage: python doc_intelligence_poc.py <path_to_scanned_pdf> [model_id]")
    #     sys.exit(1)

    #pdf_path = Path(sys.argv[1])
    pdf_path = Path("/Users/kmanojkumar/Downloads/epublication_github/code/qpg-generator/poc_samples/test.pdf")
    #model_id = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_MODEL_ID
    model_id = DEFAULT_MODEL_ID

    try:
        client = get_client()
        result = analyze_pdf(client, pdf_path, model_id)
        summary = build_summary(pdf_path, model_id, result)

        # Same directory as the input PDF, same base name, .json extension
        output_path = pdf_path.with_suffix(".json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        logger.info("Extracted %d page(s), %d table(s).", summary["page_count"], len(summary["tables"]))
        logger.info("Output written to: %s", output_path)

    except HttpResponseError as e:
        logger.error("Document Intelligence API error: %s", e.message)
        sys.exit(1)
    except (EnvironmentError, FileNotFoundError) as e:
        logger.error(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()