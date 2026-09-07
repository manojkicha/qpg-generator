"""End-to-end local demo: ingest a PDF into the configured vector store, then
generate a question paper from a JSON specification.

Exercises the same services the FastAPI job pipeline uses
(app/api/v1/question_papers.py:run_generation_pipeline), so it's a good way
to sanity-check your VECTOR_STORE_PROVIDER setup (local / qdrant /
azure_ai_search) end-to-end without needing to run the API server and poll
job status.

Prerequisites:
  - .env configured (see .env.example) — in particular VECTOR_STORE_PROVIDER,
    and LLM_PROVIDER / EMBEDDING_PROVIDER pointing at a running model
    (e.g. Ollama with `ollama pull llama3:8b` and `ollama pull nomic-embed-text`).
  - If VECTOR_STORE_PROVIDER=qdrant: Qdrant running (e.g.
    `docker run -p 6333:6333 -p 6334:6334 qdrant/qdrant`).

Usage:
    python scripts/demo_ingest_and_generate.py
    python scripts/demo_ingest_and_generate.py --pdf data/sample-maths.pdf \
        --document-id demo-maths-001 --spec sample_specification.json
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("demo")


async def main(pdf_path: str, document_id: str, spec_path: str, tenant_id: str, out_dir: str) -> None:
    from app.core.config import settings
    from app.services import IngestionService, SearchService, GenerationService
    from app.services.compilation_service import CompilationService
    from app.services.ingestion_service import ChunkMetadata
    from app.services.pdf_rendering_service import PDFRenderingService

    logger.info("Vector store provider: %s", settings.vector_store_provider)
    logger.info("LLM provider: %s | Embedding provider: %s", settings.llm_provider, settings.embedding_provider)

    spec = json.loads(Path(spec_path).read_text())

    # ── Step 1: Ingest the PDF into the configured vector store ────────────
    logger.info("Ingesting %s as document_id=%s ...", pdf_path, document_id)
    ingestion = IngestionService()
    try:
        chunk_ids = await ingestion.process_document(
            document_id=document_id,
            document_path=pdf_path,
        )
        logger.info("Ingested %d chunks", len(chunk_ids))
    finally:
        await ingestion.close()

    # ── Step 2: Retrieve context for the specification's subject/title ─────
    query = f"{spec.get('subject', '')} {spec.get('title', '')}".strip()
    logger.info("Retrieving context for query: %r", query)
    search = SearchService()
    generation = GenerationService()
    try:
        search_results = await search.hybrid_search(query=query, document_id=document_id, top_k=5)
        logger.info("Retrieved %d context chunks", len(search_results))
        for r in search_results:
            logger.info("  - [%.3f] %s: %s", r.score, r.topic or r.chapter, r.content[:80].replace("\n", " "))

        context_chunks = [
            (
                r.content,
                ChunkMetadata(
                    chapter=r.chapter,
                    topic=r.topic,
                    page_range=(r.page_start, r.page_end) if r.page_start else None,
                    heading_path=r.heading_path,
                ),
            )
            for r in search_results
        ]

        # ── Step 3: Run the agentic generation pipeline ─────────────────────
        logger.info("Generating questions (this calls your configured LLM) ...")
        result = await generation.generate_questions(
            job_id=f"demo-{document_id}",
            specification=spec,
            context_chunks=context_chunks,
        )
        logger.info("Generated %d questions", len(result.questions))
    finally:
        await search.close()
        await generation.close()

    # ── Step 4: Compile into question paper + answer key JSON ──────────────
    compiler = CompilationService()
    compiled = compiler.compile(
        questions=result.questions,
        specification=spec,
        job_id=f"demo-{document_id}",
        tenant_id=tenant_id,
    )

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "question_paper.json").write_text(json.dumps(compiled.question_paper, indent=2))
    (out / "answer_key.json").write_text(json.dumps(compiled.answer_key, indent=2))
    logger.info("Wrote %s and %s", out / "question_paper.json", out / "answer_key.json")

    # ── Step 5: Render print-ready PDFs ─────────────────────────────────────
    renderer = PDFRenderingService()
    qp_pdf = await renderer.render_question_paper(compiled.question_paper)
    ak_pdf = await renderer.render_answer_key(compiled.answer_key)
    (out / "question_paper.pdf").write_bytes(qp_pdf)
    (out / "answer_key.pdf").write_bytes(ak_pdf)
    logger.info("Wrote %s and %s", out / "question_paper.pdf", out / "answer_key.pdf")

    print("\n=== Validation summary ===")
    print(json.dumps(result.validation_summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pdf", default="data/sample-maths.pdf", help="Path to the PDF to ingest")
    parser.add_argument("--document-id", default="demo-maths-001", help="Document id to store/search under")
    parser.add_argument("--spec", default="sample_specification.json", help="Path to the specification JSON")
    parser.add_argument("--tenant-id", default="demo-tenant", help="Tenant id for the generated paper")
    parser.add_argument("--out", default="output", help="Directory to write generated files to")
    args = parser.parse_args()

    asyncio.run(main(args.pdf, args.document_id, args.spec, args.tenant_id, args.out))
