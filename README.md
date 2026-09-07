# Question Paper Generator — Module 1

AI-Powered Question Paper Generator built for Module 1 of the AI E-Publication Suite, as specified in the Solution Design Document (SDD).

## Overview

Module 1 automates the creation of question papers from eBook PDFs. It implements an agentic, multi-step generation pipeline (Plan → Generate → Validate → Compile) that produces print-ready PDFs after an optional human review step.

## Architecture

Based on SDD Section 5, the system has these layers:

- **Ingestion & Indexing Pipeline** — Document Intelligence extracts text, headings, tables, and images with layout metadata. Content is chunked by structural boundaries (chapter/section/heading) and embedded into Azure AI Search.
- **Agentic Generation Pipeline (LangGraph)** — Explicit graph of agent nodes:
  - **Planner** — Decomposes the specification into question generation tasks
  - **Retriever** — Performs hybrid search over the indexed eBook content
  - **Generator** — Generates individual questions using LLM with retrieved context
  - **Validator** — Validates generated questions against the specification
  - **Compiler** — Assembles validated questions into the final paper structure
- **Human Review Layer** — Optional admin review before final PDF rendering
- **PDF Rendering** — HTML-to-PDF service with institution-configurable templates

## Project Structure

```
question_paper_generator/
├── app/
│   ├── api/                    # FastAPI routers
│   │   └── v1/
│   │       └── question_papers.py
│   ├── core/                   # Configuration
│   │   └── config.py
│   ├── db/                     # Database setup
│   ├── models/                 # SQLAlchemy models
│   │   ├── job.py
│   │   ├── question_paper.py
│   │   ├── chunk.py
│   │   ├── answer_key.py
│   │   └── specification.py
│   ├── schemas/                # Pydantic schemas
│   │   ├── specification.py
│   │   ├── question_paper.py
│   │   ├── job.py
│   │   └── chunk.py
│   ├── services/               # Business logic
│   │   ├── ingestion_service.py
│   │   ├── generation_service.py
│   │   ├── validation_service.py
│   │   ├── compilation_service.py
│   │   ├── pdf_rendering_service.py
│   │   ├── storage_service.py
│   │   └── search_service.py
│   ├── agents/                 # LangGraph agents
│   │   ├── generation_graph.py
│   │   └── nodes/
│   │       ├── planner_node.py
│   │       ├── generator_node.py
│   │       ├── validator_node.py
│   │       └── compiler_node.py
│   ├── templates/              # Jinja2 HTML templates
│   ├── utils/                  # Utilities
│   │   └── observability.py
│   └── main.py                 # FastAPI entry point
├── tests/
│   ├── unit/
│   └── integration/
├── data/                       # Source documents
├── logs/
├── pyproject.toml
├── .env.example
└── README.md
```

## Setup

1. **Install dependencies**:
   ```bash
   pip install -e ".[dev]"
   ```

2. **Configure environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your Azure credentials
   ```

3. **Run the API**:
   ```bash
   uvicorn app.main:app --reload
   ```

4. **Run tests**:
   ```bash
   pytest
   ```

## API Contract

Based on SDD Section 12.1:

```http
POST /api/v1/question-papers/generate
Content-Type: application/json

{
  "sourceDocumentId": "uuid",
  "additionalMaterialIds": ["uuid"],
  "specification": { ... }
}

Response (202 Accepted):
{
  "jobId": "uuid",
  "status": "queued"
}
```

```http
GET /api/v1/question-papers/jobs/{jobId}

Response:
{
  "status": "completed",
  "questionPaperUrl": "https://.../question-paper.pdf",
  "answerPaperUrl": "https://.../answer-paper.pdf",
  "validationSummary": { ... }
}
```

## LLM Provider Configuration

Switch between Ollama (local), OpenAI, or Azure OpenAI by setting `LLM_PROVIDER` in `.env`:

```bash
# For local Ollama (default — uses qwen2.5-coder:14b)
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen2.5-coder:14b

# For OpenAI
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o

# For Azure OpenAI
LLM_PROVIDER=azure_openai
AZURE_OPENAI_ENDPOINT=https://...
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_DEPLOYMENT=gpt-4o
```

Same applies to `EMBEDDING_PROVIDER` — set to `ollama` (default) or `openai`.

## Technology Stack

Based on SDD Section 3:

- **AI & Data**: Azure OpenAI (GPT-4o, embeddings), Azure Document Intelligence, Azure AI Search, LangGraph
- **Backend**: Python 3.11+, FastAPI, Pydantic, SQLAlchemy (async)
- **Storage**: Azure Blob Storage, PostgreSQL, Redis
- **PDF**: WeasyPrint (HTML-to-PDF), Jinja2 templates
- **Observability**: Langfuse, MLflow

## Key Design Principles

From SDD Section 2:

1. **Agentic generation over single-prompt** — each agent step is validated before proceeding
2. **Human-in-the-loop for initial releases** — admin review before final PDF
3. **Shared core with Module 2** — ingestion, chunking, embedding, retrieval are reusable
4. **Specification-driven** — JSON spec drives the entire generation pipeline
5. **Tenant-scoped storage** — ready for multi-tenant from day one

## Observability

- **Langfuse** traces every agent step (prompts, context, output, latency, tokens)
- **MLflow** tracks prompt/template versions and evaluation runs
- **Validator flag rate** dashboard surfaces generation quality over time

## Testing

```bash
# Unit tests
pytest tests/unit/ -v

# Integration tests
pytest tests/integration/ -v

# With coverage
pytest --cov=app --cov-report=term-missing
```
