# API Contract: Question Paper Generator (Module 1)

This document defines the API contract between the Backend and the UI for the Question Paper Generator system.

## Base URL
`/api/v1`

---

## 1. Document Management
These endpoints manage the source documents that are used for question generation.

### 1.1 Upload and Ingest Document
Uploads a PDF and indexes its content into the vector store.
- **Endpoint:** `/documents/upload`
- **Method:** `POST`
- **Content-Type:** `multipart/form-data`
- **Response Code:** `201 Created`

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `file` | `file (PDF)` | Yes | The source PDF document. |
| `tenant_id` | `string` | Yes | Organization identifier. |
| `subject` | `string` | No | Subject area (e.g., EVS). |
| `grade` | `string` | No | Grade level (e.g., Grade 1). |

**Response Body:**
```json
{
  "id": "uuid-string",
  "filename": "document.pdf",
  "tenant_id": "tenant-id",
  "subject": "EVS",
  "grade": "Grade 1",
  "uploaded_at": "ISO-8601 timestamp"
}
```

### 1.2 List Subjects
Retrieves all unique subjects available for a specific tenant and grade.
- **Endpoint:** `/documents/subjects`
- **Method:** `GET`
- **Response Code:** `200 OK`

**Query Parameters:**
- `tenant_id`: (Required) The tenant identifier.
- `grade`: (Required) The grade level (e.g., "1").

**Response Body:**
```json
[
  { "subject": "Environmental Studies" },
  { "subject": "Mathematics" },
  { "subject": "English" }
]
```

### 1.3 List Documents
Retrieve a list of available source documents.
- **Endpoint:** `/documents/`
- **Method:** `GET`
- **Response Code:** `200 OK`
```

### 1.3 Get Document Details
Retrieves metadata for a specific document.
- **Endpoint:** `/documents/{document_id}`
- **Method:** `GET`
- **Response Code:** `200 OK`

### 1.4 Get Document Chunk Count
Retrieves the total number of content chunks indexed in the vector store for a document. This is useful for verifying if a document was fully ingested.
- **Endpoint:** `/documents/{document_id}/chunks/count`
- **Method:** `GET`
- **Response Code:** `200 OK`

**Response Body:**
```json
{
  "document_id": "uuid-string",
  "chunk_count": 142
}
```

---

## 2. Start Question Paper Generation
Starts an asynchronous generation job based on an existing indexed document.

- **Endpoint:** `/question-papers/generate`
- **Method:** `POST`
- **Response Code:** `202 Accepted`

### Request Body
| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `source_document_id` | `string` | Yes | ID of the source eBook document already in the system. |
| `additional_material_ids` | `array[string]` | No | IDs of additional material documents. |
| `tenant_id` | `string` | Yes | Organization/Tenant identifier. |
| `page_start` | `integer` | No | Page to start extraction from. |
| `page_end` | `integer` | No | Page to end extraction at. |
| `ocr_dpi` | `integer` | No | DPI for OCR (default: 200). |
| `specification` | `object` | Yes | The AI specification (see **Specification Schema** below). |

### Response Body
```json
{
  "job_id": "uuid-string",
  "status": "queued",
  "created_at": "ISO-8601 timestamp"
}
```

---

## 3. Get Job Status
Polls the status of a specific generation job to retrieve the final results.

- **Endpoint:** `/question-papers/jobs/{job_id}`
- **Method:** `GET`
- **Response Code:** `200 OK`

### Path Parameters
- `job_id`: The UUID of the generation job.

### Response Body
| Field | Type | Description |
| :--- | :--- | :--- |
| `job_id` | `string` | Job identifier. |
| `status` | `string` | Status: `queued` $\rightarrow$ `ingesting` $\rightarrow$ `generating` $\rightarrow$ `validating` $\rightarrow$ `review_pending` $\rightarrow$ `completed` or `failed`. |
| `current_step` | `string` | Current active pipeline step. |
| `progress_percentage` | `integer` | Completion progress (0-100). |
| `validation_summary` | `object` | Result of the AI validator (requested vs generated marks/questions). |
| `question_paper_url` | `string \| null` | Path/URL to the rendered PDF Question Paper. |
| `answer_paper_url` | `string \| null` | Path/URL to the rendered PDF Answer Key. |
| `question_paper_md_url` | `string \| null` | Path/URL to the rendered Markdown Question Paper. |
| `answer_paper_md_url` | `string \| null` | Path/URL to the rendered Markdown Answer Key. |
| `question_paper_json_url` | `string \| null` | Path/URL to the raw JSON Question Paper (detailed question types). |
| `answer_key_json_url` | `string \| null` | Path/URL to the raw JSON Answer Key. |
| `error_message` | `string \| null` | Error details if status is `failed`. |
| `completed_at` | `string \| null` | Completion timestamp. |

---

## 4. Generate from PDF Upload (POC)
Uploads a PDF directly and starts the generation process.

- **Endpoint:** `/question-papers/generate-from-pdf`
- **Method:** `POST`
- **Content-Type:** `multipart/form-data`
- **Response Code:** `202 Accepted`

### Request Form Data
| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `file` | `file (PDF)` | Yes | The source PDF document. |
| `specification` | `string (JSON)` | Yes | The AI specification JSON. |
| `tenant_id` | `string` | Yes | Organization/Tenant identifier. |

### Response Body
```json
{
  "job_id": "uuid-string",
  "status": "ingesting",
  "source_document_id": "uuid-string"
}
```

---

## 5. Generate from Blob URL (POC)
Starts generation using a PDF stored in Azure Blob Storage.

- **Endpoint:** `/question-papers/generate-from-blob-url`
- **Method:** `POST`
- **Content-Type:** `multipart/form-data`
- **Response Code:** `202 Accepted`

### Request Form Data
| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `blob_url` | `string` | Yes | Public or SAS URL to the PDF in Azure Blob. |
| `specification` | `string (JSON)` | Yes | The AI specification JSON. |
| `tenant_id` | `string` | Yes | Organization/Tenant identifier. |

### Response Body
```json
{
  "job_id": "uuid-string",
  "status": "ingesting",
  "source_document_id": "uuid-string"
}
```

---

## 6. Approve Question Paper
Marks a generated paper as approved by an admin.

- **Endpoint:** `/question-papers/jobs/{job_id}/approve`
- **Method:** `POST`
- **Response Code:** `200 OK`

### Query Parameters
- `reviewer`: (Optional) Name of the admin approving.
- `comments`: (Optional) Reviewer comments.

### Response Body
```json
{
  "message": "Question paper approved",
  "job_id": "uuid-string"
}
```

---

## Appendix: Specification Schema
The `specification` object used in the endpoints above must follow this structure:

### Specification Root
| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `title` | `string` | Yes | Paper title (e.g., "Final Term Exam"). |
| `subject` | `string` | Yes | Subject (e.g., "Environmental Studies"). |
| `academic_year` | `string` | Yes | e.g., "2025-26". |
| `duration_minutes` | `integer` | Yes | Total time for the exam. |
| `total_marks` | `integer` | Yes | Total marks for the paper. |
| `difficulty_level` | `string` | No | `easy`, `medium`, or `hard`. |
| `question_count` | `integer` | Yes | Target number of questions. |
| `category_distribution`| `array` | No | List of `CategoryDistribution` objects. |
| `mark_distribution` | `object` | Yes | `MarkDistribution` object. |
| `questions` | `array` | No | List of specific `QuestionSpecification` requirements. |

### CategoryDistribution
| Field | Type | Description |
| :--- | :--- | :--- |
| `category_name` | `string` | Topic name. |
| `min_questions` | `integer` | Min questions from this topic. |
| `max_questions` | `integer` | Max questions from this topic. |
| `min_marks` | `integer` | Min marks from this topic. |
| `max_marks` | `integer` | Max marks from this topic. |

### MarkDistribution
| Field | Type | Description |
| :--- | :--- | :--- |
| `total_marks` | `integer` | Sum of all marks. |
| `negative_marking_enabled` | `boolean` | Whether negative marks apply. |
| `negative_mark_weight` | `float` | Penalty weight (0.0 to 1.0). |
| `pass_mark` | `integer` | Minimum marks to pass. |

### QuestionSpecification
| Field | Type | Description |
| :--- | :--- | :--- |
| `question_type` | `string` | e.g., `short_answer`, `multiple_choice`, `picture_based_mcq`, `fill_in_the_blank`. |
| `topic` | `string` | Specific topic for this question. |
| `difficulty_level` | `string` | `easy`, `medium`, or `hard`. |
| `marks` | `integer` | Marks for this specific question. |
| `prompt_template` | `string` | AI prompt instructions for this question. |
 "queued",
  "created_at": "ISO-8601 timestamp"
}
```

---

## 2. Get Job Status
Polls the status of a specific generation job to retrieve the final results.

- **Endpoint:** `/question-papers/jobs/{job_id}`
- **Method:** `GET`
- **Response Code:** `200 OK`

### Path Parameters
- `job_id`: The UUID of the generation job.

### Response Body
| Field | Type | Description |
| :--- | :--- | :--- |
| `job_id` | `string` | Job identifier. |
| `status` | `string` | Status: `queued` $\rightarrow$ `ingesting` $\rightarrow$ `generating` $\rightarrow$ `validating` $\rightarrow$ `review_pending` $\rightarrow$ `completed` or `failed`. |
| `current_step` | `string` | Current active pipeline step. |
| `progress_percentage` | `integer` | Completion progress (0-100). |
| `validation_summary` | `object` | Result of the AI validator (requested vs generated marks/questions). |
| `question_paper_url` | `string \| null` | Path/URL to the rendered PDF Question Paper. |
| `answer_paper_url` | `string \| null` | Path/URL to the rendered PDF Answer Key. |
| `question_paper_md_url` | `string \| null` | Path/URL to the rendered Markdown Question Paper. |
| `answer_paper_md_url` | `string \| null` | Path/URL to the rendered Markdown Answer Key. |
| `question_paper_json_url` | `string \| null` | Path/URL to the raw JSON Question Paper (detailed question types). |
| `answer_key_json_url` | `string \| null` | Path/URL to the raw JSON Answer Key. |
| `error_message` | `string \| null` | Error details if status is `failed`. |
| `completed_at` | `string \| null` | Completion timestamp. |

---

## 3. Generate from PDF Upload (POC)
Uploads a PDF directly and starts the generation process.

- **Endpoint:** `/question-papers/generate-from-pdf`
- **Method:** `POST`
- **Content-Type:** `multipart/form-data`
- **Response Code:** `202 Accepted`

### Request Form Data
| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `file` | `file (PDF)` | Yes | The source PDF document. |
| `specification` | `string (JSON)` | Yes | The AI specification JSON. |
| `tenant_id` | `string` | Yes | Organization/Tenant identifier. |

### Response Body
```json
{
  "job_id": "uuid-string",
  "status": "ingesting",
  "source_document_id": "uuid-string"
}
```

---

## 4. Generate from Blob URL (POC)
Starts generation using a PDF stored in Azure Blob Storage.

- **Endpoint:** `/question-papers/generate-from-blob-url`
- **Method:** `POST`
- **Content-Type:** `multipart/form-data`
- **Response Code:** `202 Accepted`

### Request Form Data
| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `blob_url` | `string` | Yes | Public or SAS URL to the PDF in Azure Blob. |
| `specification` | `string (JSON)` | Yes | The AI specification JSON. |
| `tenant_id` | `string` | Yes | Organization/Tenant identifier. |

### Response Body
```json
{
  "job_id": "uuid-string",
  "status": "ingesting",
  "source_document_id": "uuid-string"
}
```

---

## 5. Approve Question Paper
Marks a generated paper as approved by an admin.

- **Endpoint:** `/question-papers/jobs/{job_id}/approve`
- **Method:** `POST`
- **Response Code:** `200 OK`

### Query Parameters
- `reviewer`: (Optional) Name of the admin approving.
- `comments`: (Optional) Reviewer comments.

### Response Body
```json
{
  "message": "Question paper approved",
  "job_id": "uuid-string"
}
```

---

## Appendix: Specification Schema
The `specification` object used in the endpoints above must follow this structure:

### Specification Root
| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `title` | `string` | Yes | Paper title (e.g., "Final Term Exam"). |
| `subject` | `string` | Yes | Subject (e.g., "Environmental Studies"). |
| `academic_year` | `string` | Yes | e.g., "2025-26". |
| `duration_minutes` | `integer` | Yes | Total time for the exam. |
| `total_marks` | `integer` | Yes | Total marks for the paper. |
| `difficulty_level` | `string` | No | `easy`, `medium`, or `hard`. |
| `question_count` | `integer` | Yes | Target number of questions. |
| `category_distribution`| `array` | No | List of `CategoryDistribution` objects. |
| `mark_distribution` | `object` | Yes | `MarkDistribution` object. |
| `questions` | `array` | No | List of specific `QuestionSpecification` requirements. |

### CategoryDistribution
| Field | Type | Description |
| :--- | :--- | :--- |
| `category_name` | `string` | Topic name. |
| `min_questions` | `integer` | Min questions from this topic. |
| `max_questions` | `integer` | Max questions from this topic. |
| `min_marks` | `integer` | Min marks from this topic. |
| `max_marks` | `integer` | Max marks from this topic. |

### MarkDistribution
| Field | Type | Description |
| :--- | :--- | :--- |
| `total_marks` | `integer` | Sum of all marks. |
| `negative_marking_enabled` | `boolean` | Whether negative marks apply. |
| `negative_mark_weight` | `float` | Penalty weight (0.0 to 1.0). |
| `pass_mark` | `integer` | Minimum marks to pass. |

### QuestionSpecification
| Field | Type | Description |
| :--- | :--- | :--- |
| `question_type` | `string` | e.g., `short_answer`, `multiple_choice`, `picture_based_mcq`, `fill_in_the_blank`. |
| `topic` | `string` | Specific topic for this question. |
| `difficulty_level` | `string` | `easy`, `medium`, or `hard`. |
| `marks` | `integer` | Marks for this specific question. |
| `prompt_template` | `string` | AI prompt instructions for this question. |
