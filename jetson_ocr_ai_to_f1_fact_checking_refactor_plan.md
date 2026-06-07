# Jetson OCR AI to F1 Fact-Checking System Refactor Plan

## Purpose

This document defines a refactor plan for reusing the completed **Jetson OCR AI** project as the foundation for a new **F1 Fact-Checking System**.

The original project already provides a working Jetson-based stack with:

- a public `web-app`
- a private `ocr-service`
- a private `llm-service`
- Docker Compose wiring
- local model mounting
- local runtime data storage
- session and account support

The new project should keep the useful runtime foundation, but change the product goal from **OCR + document question answering** to **Formula 1 news fact-checking**.

The new system should support three input types:

```text
User input
├── Plain text
├── URL to an F1 news article
└── Screenshot/image of an F1 news article
```

All input types should be normalized into clean text first. Then Gemma should extract checkable claims and classify each claim into one of two verification streams:

- Structured factual claims: verify with the local F1 knowledge database, SQLite, and FAISS.
- News / drama / statement claims: verify with Brave Search API and fetched web evidence.

Gemma should generate claim-level verdicts from the selected evidence stream and then produce a final explanation.

Target output area:

```text
Fact-check result
├── Overall verdict
├── Extracted claims
├── Verdict for each claim
└── Explanation from Gemma based on local DB and/or web evidence
```

## Target Service Boundary

The new project should use **four main services**:

```text
web-app
├── Public browser UI
├── User input handling
├── Session/history rendering
└── Calls fact-check-service

fact-check-service
├── Main orchestration service
├── Text / URL / image input preprocessing
├── Claim extraction workflow
├── Claim classification workflow
├── SQLite + FAISS retrieval
├── Brave Search API + web evidence retrieval
├── Claim-level verdict generation
└── Final result aggregation

ocr-service
├── Private OCR backend
├── Screenshot/image to plain text only
└── Simplified PP-OCRv5 det + rec pipeline

llm-service
├── Private Gemma wrapper
├── Structured claim extraction
├── Verdict generation
└── Optional general answer endpoint for debugging
```

`web-app` should remain the only public-facing container. The other three services should stay private on the Docker network.

---

# Part 1 — Project Structure Refactor

## 1. Refactor Goals

The first refactor step should clean the current Jetson OCR AI repository so the project is ready for F1 fact-checking implementation.

Main goals:

1. Keep the proven Docker/runtime foundation.
2. Remove OCR-specific UI concepts that are no longer part of the product.
3. Simplify the OCR service to screenshot text extraction only.
4. Add a new fact-checking service as the central orchestrator.
5. Add a clean knowledge database area for SQLite, FAISS, source data, and sync scripts.
6. Move old OCR design documents and unused OCR pipeline code to an archive instead of mixing them with active code.
7. Keep external model storage outside the repository.

## 2. Proposed Clean Directory Structure

After the refactor, the repository should look like this:

```text
/
├── README.md
├── docker-compose.yml
├── start_app.sh
├── stop_app.sh
├── .env.example
│
├── configs/
│   ├── models.host.env
│   ├── models.container.env
│   ├── app.env.example
│   ├── fact_check.env.example
│   └── url_fetch.env.example
│
├── docker/
│   ├── Dockerfile.web
│   ├── Dockerfile.ocr
│   ├── Dockerfile.llm
│   ├── Dockerfile.fact_check
│   └── paddleocr-l4t-base/
│
├── requirements/
│   ├── web.txt
│   ├── ocr.txt
│   ├── llm.txt
│   └── fact_check.txt
│
├── src/
│   ├── web_app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── store.py
│   │   ├── auth.py
│   │   ├── clients/
│   │   │   ├── __init__.py
│   │   │   └── fact_check_client.py
│   │   ├── templates/
│   │   │   └── index.html
│   │   └── static/
│   │       ├── app.css
│   │       ├── app.js
│   │       └── icons/
│   │
│   ├── fact_check_service/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── schemas.py
│   │   ├── orchestrator.py
│   │   ├── input_router.py
│   │   ├── text_preprocess.py
│   │   ├── url_ingest.py
│   │   ├── ocr_client.py
│   │   ├── llm_client.py
│   │   ├── retrieval.py
│   │   ├── web_search.py
│   │   ├── web_evidence.py
│   │   ├── verdict.py
│   │   ├── aggregation.py
│   │   ├── evidence_formatter.py
│   │   ├── prompts/
│   │   │   ├── claim_extraction.md
│   │   │   └── verdict_generation.md
│   │   └── knowledge/
│   │       ├── __init__.py
│   │       ├── sqlite_store.py
│   │       ├── vector_store.py
│   │       ├── aliases.py
│   │       ├── fact_generator.py
│   │       ├── dataset_importer.py
│   │       ├── jolpica_sync.py
│   │       └── embeddings.py
│   │
│   ├── ocr_service/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── pipeline.py
│   │   ├── paddle_adapter.py
│   │   ├── image_ops.py
│   │   ├── schemas.py
│   │   └── local_infer.py
│   │
│   └── llm_service/
│       ├── __init__.py
│       ├── main.py
│       ├── config.py
│       ├── schemas.py
│       ├── llama_client.py
│       ├── prompt_builder.py
│       └── json_repair.py
│
├── scripts/
│   ├── build_f1_database.py
│   ├── sync_jolpica.py
│   ├── rebuild_faiss_index.py
│   ├── inspect_fact.py
│   ├── smoke_test_text_check.py
│   ├── smoke_test_url_check.py
│   └── smoke_test_image_check.py
│
├── data/
│   ├── fact_check/
│   │   ├── requests/
│   │   ├── results/
│   │   └── sessions/
│   ├── knowledge_db/
│   │   ├── f1.sqlite
│   │   ├── faiss.index
│   │   ├── fact_metadata.jsonl
│   │   └── build_manifest.json
│   ├── source_data/
│   │   ├── formula_1_world_championship/
│   │   └── jolpica_cache/
│   ├── uploads/
│   └── web_app/
│
├── docs/
│   ├── DIRECTORY_STRUCTURE.md
│   ├── F1_FACT_CHECKING_ARCHITECTURE.md
│   ├── API_CONTRACTS.md
│   ├── KNOWLEDGE_DATABASE.md
│   ├── DEPLOYMENT.md
│   └── archive/
│       └── jetson_ocr_ai/
│           ├── ocr_service.md
│           ├── web_app.md
│           ├── llm_service.md
│           └── base_doc.md
│
├── tests/
│   ├── test_text_preprocess.py
│   ├── test_url_ingest.py
│   ├── test_fact_generation.py
│   ├── test_retrieval.py
│   └── test_verdict_schema.py
│
├── third_party/
│   └── llama-bin/
│
└── wheels/
```

## 3. Files and Folders to Keep

Keep these parts from Jetson OCR AI:

| Path | Action | Reason |
|---|---|---|
| `src/web_app/` | Keep and refactor | Reuse UI shell, auth/session logic, static asset handling, and backend client pattern. |
| `src/ocr_service/` | Keep but simplify heavily | Reuse FastAPI service, PaddleOCR runtime setup, model loading, and image handling. |
| `src/llm_service/` | Keep and refactor | Reuse local Gemma/llama-server integration. |
| `docker/` | Keep and update | Existing Jetson Docker setup is valuable. |
| `docker-compose.yml` | Keep and modify | Add `fact-check-service`; update dependencies and service URLs. |
| `requirements/` | Keep and extend | Add `fact_check.txt`; simplify `ocr.txt` if possible. |
| `configs/models.*.env` | Keep and reduce | Keep only active model paths for OCR, LLM, and embeddings. |
| `third_party/llama-bin/` | Keep | Still required by `llm-service`. |
| `wheels/` | Keep | Still required for Jetson-compatible Paddle runtime. |
| `start_app.sh`, `stop_app.sh` | Keep and update | Preserve local development workflow. |

## 4. Files and Folders to Add

Add these components for the new project.

### 4.1. New `fact-check-service`

```text
src/fact_check_service/
```

This becomes the central backend for F1 verification.

Responsibilities:

- accept normalized check requests from `web-app`
- decide input path: text, URL, or image
- call `ocr-service` for screenshot/image input
- fetch and clean URL article content
- call `llm-service` for claim extraction
- call `llm-service` for claim classification
- query SQLite and FAISS for structured factual evidence
- call Brave Search API for news/drama/statement claims
- fetch and rank web evidence from the top search results
- call `llm-service` for verdict generation
- aggregate claim verdicts into the final result

### 4.2. New knowledge database package

```text
src/fact_check_service/knowledge/
```

This package owns all local F1 knowledge database logic.

It should include:

- dataset import from Formula 1 World Championship CSV files
- Jolpica update sync
- alias normalization
- fact generation
- SQLite store
- FAISS vector store
- embedding generation
- index rebuild utilities

### 4.3. New runtime data folders

```text
data/knowledge_db/
data/source_data/
data/fact_check/
```

Suggested meaning:

| Path | Purpose |
|---|---|
| `data/source_data/formula_1_world_championship/` | Raw Kaggle/CSV dataset files. |
| `data/source_data/jolpica_cache/` | Cached Jolpica API responses for reproducible updates. |
| `data/knowledge_db/f1.sqlite` | Main structured knowledge database. |
| `data/knowledge_db/faiss.index` | Vector index for `fact_text`. |
| `data/knowledge_db/fact_metadata.jsonl` | Mapping from FAISS vector IDs to SQLite `fact_id`. |
| `data/knowledge_db/build_manifest.json` | Build version, source versions, embedding model, and timestamps. |
| `data/fact_check/requests/` | Optional saved input payloads for debugging. |
| `data/fact_check/results/` | Optional saved fact-check result JSON. |
| `data/fact_check/sessions/` | Optional session-level artifacts. |

### 4.4. New scripts

```text
scripts/build_f1_database.py
scripts/sync_jolpica.py
scripts/rebuild_faiss_index.py
scripts/inspect_fact.py
scripts/smoke_test_text_check.py
scripts/smoke_test_url_check.py
scripts/smoke_test_image_check.py
```

Purpose:

- `build_f1_database.py`: build SQLite + FAISS from local CSV files.
- `sync_jolpica.py`: update SQLite from Jolpica.
- `rebuild_faiss_index.py`: rebuild only the vector index from existing facts.
- `inspect_fact.py`: debug facts by season, race, driver, team, or relation.
- `smoke_test_*`: verify the end-to-end paths before UI testing.

## 5. Files and Folders to Remove or Archive

Do not immediately delete working code. First move old OCR-specific files into `docs/archive/` or `src/archive/` until the new system is stable.

### 5.1. Archive old documentation

Move old project-specific docs:

```text
docs/archive/jetson_ocr_ai/
├── ocr_service.md
├── web_app.md
├── llm_service.md
└── base_doc.md
```

Then create new active docs:

```text
docs/F1_FACT_CHECKING_ARCHITECTURE.md
docs/API_CONTRACTS.md
docs/KNOWLEDGE_DATABASE.md
docs/DEPLOYMENT.md
docs/DIRECTORY_STRUCTURE.md
```

### 5.2. Remove old OCR UI concepts

From the active UI, remove or replace:

| Old OCR UI element | New F1 fact-checking behavior |
|---|---|
| OCR result panel | Replace with `Fact-check result`. |
| OCR copy button | Remove. |
| Quick action: `Answer the question(s)` | Replace with `Check F1 news`. |
| Quick action: `Solve this problem` | Remove. |
| OCR Markdown preview | Remove from the main product UI. Keep raw extracted text only in a debug panel if needed. |
| Document QA prompt flow | Replace with fact-check request flow. |

### 5.3. Remove unused OCR model paths from active config

The F1 screenshot OCR path only needs:

```text
PP-OCRv5_mobile_det_infer
PP-OCRv5_mobile_rec_infer
```

Move these old model paths out of active config:

```text
PP-LCNet_x1_0_doc_ori_infer
UVDoc_infer
PP-LCNet_x0_25_textline_ori_infer
PP-DocLayout_plus-L_infer
PP-DocBlockLayout_infer
PP-FormulaNet_plus-S_infer
```

They can stay in external model storage, but they should not be loaded by the new runtime.

### 5.4. Archive unused OCR pipeline code

Archive or remove code related to:

- document orientation classification
- document image unwarping
- layout detection
- region detection
- formula recognition
- formula masking
- structured Markdown assembly
- document block reconstruction
- formula-specific benchmarking

Keep only:

- image loading
- optional dark-background normalization
- text detection
- text recognition
- line sorting
- plain text output

## 6. New Configuration Layout

### 6.1. `configs/models.host.env`

Example:

```bash
# OCR
OCR_DET_MODEL_DIR=/home/viettran_orin/models/PP-OCRv5_mobile_det_infer
OCR_REC_MODEL_DIR=/home/viettran_orin/models/PP-OCRv5_mobile_rec_infer

# LLM
LLM_MODEL_PATH=/home/viettran_orin/models/llm/gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf

# Embedding
EMBEDDING_MODEL_DIR=/home/viettran_orin/models/embeddings/all-MiniLM-L6-v2
```

### 6.2. `configs/models.container.env`

Example:

```bash
# OCR
OCR_DET_MODEL_DIR=/models/PP-OCRv5_mobile_det_infer
OCR_REC_MODEL_DIR=/models/PP-OCRv5_mobile_rec_infer

# LLM
LLM_MODEL_PATH=/models/llm/gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf

# Embedding
EMBEDDING_MODEL_DIR=/models/embeddings/all-MiniLM-L6-v2
```

### 6.3. `configs/fact_check.env.example`

```bash
FACT_DB_PATH=/data/knowledge_db/f1.sqlite
FACT_FAISS_INDEX_PATH=/data/knowledge_db/faiss.index
FACT_METADATA_PATH=/data/knowledge_db/fact_metadata.jsonl
FACT_TOP_K=8
FACT_STRUCTURED_SQL_FIRST=1
FACT_MIN_VECTOR_SCORE=0.35

OCR_SERVICE_URL=http://ocr-service:8080
LLM_SERVICE_URL=http://llm-service:8081

URL_FETCH_TIMEOUT_SECONDS=10
URL_FETCH_MAX_BYTES=3000000
URL_ALLOWED_SCHEMES=http,https

FACT_SAVE_REQUEST_ARTIFACTS=1

BRAVE_SEARCH_API_KEY=${BRAVE_SEARCH_API_KEY}
BRAVE_SEARCH_ENDPOINT=https://api.search.brave.com/res/v1/web/search
BRAVE_SEARCH_TOP_N=3
WEB_EVIDENCE_FETCH_TIMEOUT_SECONDS=10
WEB_EVIDENCE_MAX_CHARS_PER_SOURCE=12000
```

`BRAVE_SEARCH_API_KEY` is a secret. Store the real value in the project-root `.env`, in the same group as `WEB_APP_SECRET_KEY`, SMTP username/password, and other deployment secrets. Example:

```bash
BRAVE_SEARCH_API_KEY=change-me
```

## 7. Updated Docker Compose Shape

The new Compose stack should have four app services:

```yaml
services:
  web-app:
    build:
      context: .
      dockerfile: docker/Dockerfile.web
    depends_on:
      - fact-check-service
    environment:
      FACT_CHECK_SERVICE_URL: http://fact-check-service:8082
    ports:
      - "8080:8080"

  fact-check-service:
    build:
      context: .
      dockerfile: docker/Dockerfile.fact_check
    depends_on:
      - ocr-service
      - llm-service
    env_file:
      - configs/models.container.env
      - configs/fact_check.env
    volumes:
      - ./data:/data
      - /home/viettran_orin/models:/models:ro

  ocr-service:
    build:
      context: .
      dockerfile: docker/Dockerfile.ocr
    env_file:
      - configs/models.container.env
    volumes:
      - ./data:/data
      - /home/viettran_orin/models:/models:ro

  llm-service:
    build:
      context: .
      dockerfile: docker/Dockerfile.llm
    env_file:
      - configs/models.container.env
    volumes:
      - /home/viettran_orin/models:/models:ro
      - ./third_party:/third_party:ro
```

Port suggestions:

| Service | Internal port | Public? |
|---|---:|---|
| `web-app` | `8080` | Yes |
| `ocr-service` | `8080` or `8083` | No |
| `llm-service` | `8081` | No |
| `fact-check-service` | `8082` | No |

---

# Part 2 — Service-Level Refactor Work

## 1. `web-app`

### 1.1. New Role

`web-app` should become the public UI and session layer for F1 fact-checking.

It should no longer behave like an OCR assistant. It should not expose raw OCR output as the main result. OCR becomes an internal preprocessing step only for screenshot input.

### 1.2. UI Changes

Replace the old OCR assistant interface with an F1 fact-checking interface.

#### Header

Old:

```text
OCR AI Assistant
Extract text and get intelligent answers
```

New:

```text
F1 Fact Checker
Check Formula 1 news against local records and web evidence
```

#### Input area

The input area should support three modes:

```text
[Text] [URL] [Image]
```

Recommended UI behavior:

| Input type | UI control | Backend path |
|---|---|---|
| Plain text | Large textarea | Send text directly to `fact-check-service`. |
| URL | URL input field | `fact-check-service` fetches and cleans the article. |
| Image | Upload/paste/drop zone | `fact-check-service` calls `ocr-service`. |

The primary action button should be:

```text
Check F1 News
```

Replace quick action buttons:

| Old button | New behavior |
|---|---|
| `Answer the question(s)` | Replace with `Check F1 News`. |
| `Solve this problem` | Remove. |

#### Output area

Remove the OCR output area and copy button.

New output layout:

```text
Fact-check result
├── Overall verdict
├── Extracted claims
├── Verdict for each claim
└── Explanation
```

Suggested UI sections:

```text
Overall verdict
- SUPPORTED
- REFUTED
- MIXED
- NOT_ENOUGH_INFO

Extracted claims
- c001: ...
- c002: ...

Claim verdicts
- Claim
- Verdict
- Confidence
- Evidence
- Explanation

Final explanation
- Short Gemma-generated explanation based only on retrieved evidence
```

For debugging, optionally add a collapsible section:

```text
Debug details
├── Cleaned input text
├── OCR extracted text
├── URL metadata
└── Retrieved evidence
```

Keep this collapsed by default.

### 1.3. Web-App API Changes

The web app can expose a single internal UI endpoint:

```text
POST /sessions/check
```

Suggested request shape:

```json
{
  "input_type": "text | url | image",
  "text": "optional plain text",
  "url": "optional article URL",
  "session_id": "optional existing session id"
}
```

For images, use `multipart/form-data`:

```text
POST /sessions/check-image
field: image
field: session_id
```

The web app should call:

```text
POST http://fact-check-service:8082/v1/check
```

or:

```text
POST http://fact-check-service:8082/v1/check/text
POST http://fact-check-service:8082/v1/check/url
POST http://fact-check-service:8082/v1/check/image
```

### 1.4. Session Store Changes

The old session model stores OCR Markdown and assistant chat messages. The new model should store fact-checking artifacts.

Suggested tables:

```text
sessions
├── id
├── owner_type
├── owner_id
├── input_type
├── input_preview
├── status
├── created_at
└── updated_at

fact_check_runs
├── id
├── session_id
├── input_type
├── source_url
├── source_title
├── source_domain
├── image_path
├── cleaned_text_path
├── result_json_path
├── overall_verdict
├── elapsed_ms
├── created_at
└── updated_at

claim_results
├── id
├── run_id
├── claim_id
├── claim_text
├── claim_type
├── verdict
├── confidence
├── explanation
└── evidence_json
```

### 1.5. Frontend State Changes

Replace old states:

```text
empty
uploading
ocr_success
answering
error
```

with:

```text
empty
preprocessing
extracting_claims
retrieving_evidence
generating_verdict
completed
error
```

The UI can display a simple progress indicator:

```text
Preparing input...
Extracting claims...
Retrieving evidence...
Generating verdict...
```

### 1.6. Web-App Acceptance Checklist

- The UI supports text, URL, and image inputs.
- The old OCR result panel is removed.
- The OCR copy button is removed.
- The primary action is `Check F1 News`.
- The output area follows the required fact-check structure.
- Recent sessions show fact-check runs, not OCR jobs.
- `web-app` only calls `fact-check-service`, not `ocr-service` or `llm-service` directly for normal fact-checking.
- Public traffic still reaches only `web-app`.

---

## 2. `ocr-service`

### 2.1. New Role

`ocr-service` should become a small private screenshot-to-text service.

It should not know anything about Formula 1, claims, evidence, or verdicts.

### 2.2. Simplified Pipeline

Replace the current document OCR pipeline with:

```text
Input image
↓
Optional lightweight image normalization
↓
PP-OCRv5_mobile_det
↓
PP-OCRv5_mobile_rec
↓
Line sorting
↓
Plain text output
```

No layout detection. No formula recognition. No document unwarping. No structured Markdown.

### 2.3. Keep

Keep these files, but simplify them:

```text
src/ocr_service/main.py
src/ocr_service/config.py
src/ocr_service/pipeline.py
src/ocr_service/paddle_adapter.py
src/ocr_service/image_ops.py
src/ocr_service/local_infer.py
```

### 2.4. Replace or Simplify

#### `pipeline.py`

New responsibilities:

- load a single image
- optionally normalize dark screenshots
- run text detection
- crop detected boxes
- run text recognition
- sort lines top-to-bottom and left-to-right
- join lines into plain text
- return basic confidence and timing metadata

Target internal result:

```json
{
  "text": "clean extracted text",
  "lines": [
    {
      "text": "line text",
      "bbox": [x1, y1, x2, y2],
      "det_score": 0.98,
      "rec_score": 0.96,
      "order": 0
    }
  ],
  "warnings": [],
  "timings_ms": {
    "preprocess": 3.1,
    "detection": 24.5,
    "recognition": 38.2,
    "postprocess": 2.0,
    "total": 67.8
  }
}
```

#### `paddle_adapter.py`

Only load:

```text
PP-OCRv5_mobile_det
PP-OCRv5_mobile_rec
```

Remove active loading paths for:

```text
document orientation
document unwarping
textline orientation
layout detection
region detection
formula recognition
```

#### `config.py`

Keep only OCR options needed for screenshots:

```bash
OCR_DET_MODEL_DIR
OCR_REC_MODEL_DIR
OCR_DEVICE
OCR_USE_TENSORRT
OCR_PRELOAD_PIPELINE_ON_STARTUP
OCR_WARMUP_ON_STARTUP
OCR_DARK_BACKGROUND_NORMALIZATION
OCR_MIN_REC_SCORE
OCR_MAX_IMAGE_SIDE
```

### 2.5. API Contract

Add a new JSON endpoint:

```text
POST /v1/ocr/plain
```

Accepted input:

```text
multipart/form-data
field: image
```

Response:

```json
{
  "text": "plain OCR text",
  "lines": [],
  "warnings": [],
  "timings_ms": {},
  "meta": {
    "filename": "screenshot.png",
    "content_type": "image/png"
  }
}
```

Optional compatibility:

- Keep `POST /v1/ocr` temporarily.
- It can return plain text as `text/plain` or call the new internal path.
- Remove the Markdown-centric behavior once `web-app` and `fact-check-service` no longer depend on it.

### 2.6. Image Input Policy

For the F1 system, only screenshot/image input is required.

Recommended accepted formats:

```text
PNG
JPG
JPEG
WEBP
```

PDF support can be removed from the active path unless there is a clear need to fact-check PDF articles later.

### 2.7. OCR-Service Acceptance Checklist

- `ocr-service` starts without loading layout/formula/document models.
- Only detection and recognition models are required.
- `POST /v1/ocr/plain` returns plain text JSON.
- Screenshot OCR works on normal and dark-mode news screenshots.
- OCR output is not presented directly as a product result.
- OCR failures are returned to `fact-check-service` with clear error codes.

---

## 3. `llm-service`

### 3.1. New Role

`llm-service` should remain a private wrapper around local Gemma/llama-server.

It should not directly access SQLite, FAISS, Jolpica, or the F1 dataset. It should only perform language-model tasks requested by `fact-check-service`.

### 3.2. Required LLM Tasks

The new F1 system needs two main LLM tasks:

```text
[1] Claim extraction
Input: cleaned article/text/OCR text
Output: structured checkable claims

[2] Verdict generation
Input: claim + retrieved evidence
Output: SUPPORTS / REFUTES / NOT_ENOUGH_INFO + explanation
```

Optional third task:

```text
[3] Final aggregation explanation
Input: claim verdicts
Output: concise final explanation
```

### 3.3. Endpoint Options

Recommended approach: keep the generic `POST /v1/answer` endpoint for debugging, but add task-specific structured endpoints.

```text
GET  /healthz
POST /v1/extract-claims
POST /v1/generate-verdict
POST /v1/summarize-verdicts
POST /v1/answer              # optional debug/general endpoint
```

### 3.4. Claim Extraction Contract

Request:

```json
{
  "clean_text": "F1 article text...",
  "source_metadata": {
    "source_type": "text | url | image",
    "title": "optional",
    "source_domain": "optional",
    "published_at": "optional"
  },
  "max_claims": 12
}
```

Response:

```json
{
  "claims": [
    {
      "claim_id": "c001",
      "claim": "Max Verstappen won the 2021 Abu Dhabi Grand Prix.",
      "claim_type": "race_result",
      "verification_stream": "structured",
      "entities": {
        "driver": "Max Verstappen",
        "constructor": null,
        "race": "Abu Dhabi Grand Prix",
        "season": 2021,
        "position": 1,
        "circuit": null
      },
      "needs_fact_check": true
    }
  ],
  "warnings": []
}
```

### 3.5. Verdict Generation Contract

Request:

```json
{
  "claim": {
    "claim_id": "c001",
    "claim": "Max Verstappen won the 2021 Abu Dhabi Grand Prix.",
    "claim_type": "race_result",
    "entities": {}
  },
  "evidence": [
    {
      "fact_id": "fact_2021_abudhabi_p1",
      "fact_text": "Max Verstappen won the 2021 Abu Dhabi Grand Prix.",
      "source": "Formula 1 World Championship Dataset",
      "score": 0.91
    }
  ]
}
```

Response:

```json
{
  "claim_id": "c001",
  "verdict": "SUPPORTS",
  "confidence": "high",
  "evidence_used": ["fact_2021_abudhabi_p1"],
  "explanation": "The retrieved evidence states that Max Verstappen won the 2021 Abu Dhabi Grand Prix."
}
```

Allowed claim verdict labels:

```text
SUPPORTS
REFUTES
NOT_ENOUGH_INFO
```

Overall verdict labels:

```text
SUPPORTED
REFUTED
MIXED
NOT_ENOUGH_INFO
```

### 3.6. JSON Reliability

Because the fact-checking pipeline depends on structured output, add safeguards:

- strict JSON schema validation in `llm-service`
- one retry with a correction prompt when JSON is invalid
- optional `json_repair.py` helper for minor formatting issues
- clear failure response if the model cannot produce valid JSON

### 3.7. Prompt Files

Keep prompts versioned as files:

```text
src/fact_check_service/prompts/claim_extraction.md
src/fact_check_service/prompts/verdict_generation.md
```

Alternatively, if prompt ownership stays inside `llm-service`:

```text
src/llm_service/prompts/f1_claim_extraction.md
src/llm_service/prompts/f1_verdict_generation.md
```

Recommended ownership:

- `fact-check-service` owns F1-specific prompt text.
- `llm-service` owns generic model execution and JSON validation.

This keeps `llm-service` reusable for future projects.

### 3.8. LLM-Service Acceptance Checklist

- Gemma still runs through local `llama-server`.
- `llm-service` supports structured claim extraction.
- `llm-service` supports structured verdict generation.
- Invalid JSON responses are retried or rejected cleanly.
- The service does not directly query the knowledge database.
- Hidden chain-of-thought is not exposed; only concise user-facing explanations are returned.

---

## 4. `fact-check-service`

### 4.1. New Role

`fact-check-service` is the central backend of the new project.

It owns the full F1 fact-checking workflow:

```text
Input
↓
Preprocess into clean text
↓
Extract claims with Gemma
↓
Classify claims with Gemma
├── Structured factual claim
│   └── Retrieve evidence from SQLite + FAISS
│
└── News / drama / statement claim
    └── Retrieve evidence from Brave Search API + fetched web articles
↓
Generate verdicts with Gemma
↓
Aggregate final result
↓
Return structured fact-check result
```

### 4.2. API Surface

Recommended endpoints:

```text
GET  /healthz
POST /v1/check
POST /v1/check/text
POST /v1/check/url
POST /v1/check/image
GET  /v1/facts/{fact_id}
GET  /v1/debug/search
```

The unified endpoint can accept JSON:

```json
{
  "input_type": "text",
  "text": "Verstappen won the 2021 Abu Dhabi Grand Prix.",
  "options": {
    "top_k": 8,
    "save_artifacts": true
  }
}
```

URL request:

```json
{
  "input_type": "url",
  "url": "https://example.com/f1-news",
  "options": {
    "top_k": 8
  }
}
```

Image request should use `multipart/form-data`:

```text
field: image
field: options_json
```

### 4.3. Standard Response Shape

Return a stable result shape for the web app:

```json
{
  "run_id": "run_20260607_001",
  "input_type": "url",
  "source": {
    "url": "https://example.com/f1-news",
    "title": "Example F1 Article",
    "source_domain": "example.com",
    "published_at": "2025-04-10"
  },
  "overall_verdict": "MIXED",
  "extracted_claims": [
    {
      "claim_id": "c001",
      "claim": "Max Verstappen won the 2021 Abu Dhabi Grand Prix.",
      "claim_type": "race_result",
      "entities": {
        "driver": "Max Verstappen",
        "race": "Abu Dhabi Grand Prix",
        "season": 2021,
        "position": 1
      }
    }
  ],
  "claim_verdicts": [
    {
      "claim_id": "c001",
      "claim": "Max Verstappen won the 2021 Abu Dhabi Grand Prix.",
      "verdict": "SUPPORTS",
      "confidence": "high",
      "verification_stream": "structured",
      "verified_by": "local_knowledge_database",
      "evidence": [
        {
          "fact_id": "fact_2021_abudhabi_p1",
          "fact_text": "Max Verstappen won the 2021 Abu Dhabi Grand Prix.",
          "source": "Formula 1 World Championship Dataset",
          "score": 0.91
        }
      ],
      "explanation": "The local database supports this claim."
    }
  ],
  "explanation": "Most claims are supported. Structured claims were checked against the local database, while news/drama/statement claims were checked against web evidence.",
  "warnings": [],
  "timings_ms": {
    "preprocess": 120,
    "claim_extraction": 1800,
    "retrieval": 40,
    "verdict_generation": 2200,
    "total": 4160
  }
}
```

### 4.4. Input Preprocessing

#### Plain text path

```text
[1] Receive text
[2] Normalize whitespace
[3] Remove obvious UI/newsletter noise if pasted from a web page
[4] Trim to maximum input length
[5] Send to claim extraction
```

#### URL path

```text
[1] Validate URL scheme: http or https only
[2] Fetch HTML with timeout and maximum response size
[3] Reject unsupported content types
[4] Extract main article body
[5] Remove boilerplate: menus, ads, cookie banners, newsletter prompts, comments
[6] Preserve metadata: title, author, published_at, domain, canonical URL
[7] Normalize text
[8] Chunk if the article is too long
[9] Send cleaned text to claim extraction
```

Recommended libraries:

```text
trafilatura
readability-lxml
beautifulsoup4
lxml
```

For v1, use one primary extractor and one fallback extractor:

```text
primary: trafilatura
fallback: readability-lxml + BeautifulSoup cleanup
```

#### Image path

```text
[1] Receive screenshot/image
[2] Validate image type
[3] Forward image to ocr-service
[4] Receive plain OCR text
[5] Clean OCR artifacts
[6] Send cleaned OCR text to claim extraction
```

`fact-check-service` should not expose OCR text as the main output, but it can save it as a debug artifact.

### 4.5. Claim Extraction

`fact-check-service` calls `llm-service` with cleaned text and expects structured claims.

Rules:

- Claims must be Formula 1-related to be fact-checked.
- Non-F1 claims should be labeled `not_f1_claim`.
- Vague claims should be labeled `unclear`.
- Claims without enough concrete entities should either be skipped or marked `NOT_ENOUGH_INFO`.
- Each claim must be classified into a verification stream before evidence retrieval.

Recommended claim types:

```text
race_result
qualifying_result
driver_standing
constructor_standing
championship_result
race_calendar
circuit_info
team_driver_relation
statement
contract_news
controversy
personal_life
rumor
breaking_news
not_f1_claim
unclear
```

Recommended verification streams:

```text
structured
web
not_f1_claim
unclear
```

Classification rule:

- Use `structured` for stable records that belong in the local knowledge database.
- Use `web` for public statements, interviews, rumors, controversies, contracts, personal-life claims, and current news.
- Use `not_f1_claim` for claims outside Formula 1.
- Use `unclear` when Gemma cannot identify a checkable claim or cannot route it safely.

### 4.6. Evidence Retrieval

Use separate retrieval paths based on `verification_stream`.

#### Structured factual claim retrieval

Use two local retrieval methods:

```text
Structured SQLite retrieval
+
FAISS semantic retrieval
```

#### Structured retrieval

Use SQLite first when the extracted claim has clear entities:

| Claim type | SQLite query focus |
|---|---|
| `race_result` | season + race + driver + finishing position |
| `qualifying_result` | season + race + driver + qualifying position |
| `driver_standing` | season + driver + standing position/points |
| `constructor_standing` | season + constructor + standing position/points |
| `championship_result` | season + driver/constructor champion |
| `race_calendar` | season + race + date/circuit |
| `circuit_info` | race/circuit/country/location |
| `team_driver_relation` | season + driver + constructor/team |

#### FAISS retrieval

Use semantic retrieval on `fact_text` for flexible phrasing.

Example:

```text
Claim:
"Verstappen took victory in Abu Dhabi 2021."

Top FAISS fact:
"Max Verstappen won the 2021 Abu Dhabi Grand Prix."
```

#### Evidence merging

Merge structured and semantic evidence:

```text
[1] Collect SQL evidence
[2] Collect FAISS top-k evidence
[3] Deduplicate by fact_id
[4] Sort by source priority and retrieval score
[5] Keep the final top evidence set
```

Suggested source priority:

```text
structured SQL exact match > FAISS high score > FAISS lower score
```

#### News / drama / statement claim retrieval

Use Brave Search API and fetched web article text.

```text
Claim
↓
Generate search query with Gemma
↓
Brave Search API
↓
Fetch top n search results, default n=3
↓
Fetch full article text
↓
Rank evidence by relevance and reliability
↓
Gemma compares claim with web evidence
↓
Verdict: SUPPORTS / REFUTES / NOT_ENOUGH_INFO
```

Reliability ranking should prefer:

- Official sources: FIA, Formula 1, teams, drivers, race organizers, and published statements.
- Established motorsport outlets with named authors and clear publication dates.
- Sources that directly quote the relevant person or organization.
- Multiple independent sources over one weak or rumor-only article.

Suggested source priority:

```text
official source > direct quote/interview > reputable motorsport outlet > syndicated/general news > rumor/aggregation site
```

The evidence object for web claims should include title, URL, source domain, publication date when available, snippet or extracted passage, reliability label, and relevance score.

### 4.7. Verdict Generation

For each claim, send the claim and evidence to `llm-service`.

The model must only use retrieved evidence. It must not invent race results, statements, rumors, or news context from general knowledge.

Rules:

- If evidence directly supports the claim: `SUPPORTS`
- If evidence contradicts the claim: `REFUTES`
- If evidence is missing or too weak: `NOT_ENOUGH_INFO`

The verdict output must clearly state the verification source:

```text
verified_by = local_knowledge_database
verified_by = brave_search_web_evidence
verified_by = local_knowledge_database_and_web_evidence
```

### 4.8. Overall Verdict Aggregation

Suggested aggregation rules:

```text
If all checked claims are SUPPORTS:
    overall_verdict = SUPPORTED

If all checked claims are REFUTES:
    overall_verdict = REFUTED

If there is a mix of SUPPORTS and REFUTES:
    overall_verdict = MIXED

If most claims are NOT_ENOUGH_INFO and no claim is REFUTES:
    overall_verdict = NOT_ENOUGH_INFO

If there are no checkable F1 claims:
    overall_verdict = NOT_ENOUGH_INFO
```

The final explanation should summarize:

- how many claims were extracted
- how many were supported
- how many were refuted
- which claims lacked enough evidence
- which claims used the local F1 knowledge database
- which claims used Brave Search web evidence
- which sources were most important for the final result

### 4.9. Knowledge Database Build

The knowledge database should be built before runtime fact-checking.

Build flow:

```text
Formula 1 World Championship CSV files
↓
Normalize tables
↓
Import into SQLite
↓
Generate natural-language facts
↓
Embed fact_text with all-MiniLM-L6-v2
↓
Build FAISS index
↓
Save manifest
```

Update flow:

```text
Check latest local season
↓
Fetch missing/new data from Jolpica
↓
Upsert into SQLite
↓
Regenerate affected facts
↓
Embed new/changed facts
↓
Rebuild or update FAISS index
```

Important rule:

```text
Jolpica should update the local SQLite database before fact-checking.
It should not be called directly during a normal user fact-check request.
```

### 4.10. Fact Table

Recommended `facts` table:

```sql
CREATE TABLE facts (
    fact_id TEXT PRIMARY KEY,
    fact_text TEXT NOT NULL,
    subject TEXT,
    relation TEXT,
    object TEXT,
    season INTEGER,
    race_id TEXT,
    driver_id TEXT,
    constructor_id TEXT,
    source TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

Suggested indexes:

```sql
CREATE INDEX idx_facts_season ON facts(season);
CREATE INDEX idx_facts_race_id ON facts(race_id);
CREATE INDEX idx_facts_driver_id ON facts(driver_id);
CREATE INDEX idx_facts_constructor_id ON facts(constructor_id);
CREATE INDEX idx_facts_relation ON facts(relation);
```

### 4.11. Fact-Check-Service Acceptance Checklist

- Text, URL, and image inputs all become clean text.
- Gemma is always used for claim extraction.
- Gemma is used again for claim classification.
- SQLite + FAISS evidence retrieval works locally for structured claims.
- Brave Search API + fetched web evidence works for news/drama/statement claims.
- Jolpica sync is an offline/admin update path, not a runtime verification path.
- Each claim gets `SUPPORTS`, `REFUTES`, or `NOT_ENOUGH_INFO`.
- The response contains `overall_verdict`, `extracted_claims`, `claim_verdicts`, and `explanation`.
- All generated explanations are grounded in retrieved evidence.
- Each claim verdict clearly states whether it was verified by local DB evidence, Brave web evidence, or both.
- Debug artifacts can be saved but are not required for the main UI.

---

# Suggested Implementation Order

## Phase 0 — Create a refactor branch

```bash
git checkout -b refactor/f1-fact-checking-system
```

Create an archive folder:

```bash
mkdir -p docs/archive/jetson_ocr_ai
```

Move old docs into the archive before rewriting active docs.

## Phase 1 — Clean structure and config

Tasks:

- Add `src/fact_check_service/`.
- Add `requirements/fact_check.txt`.
- Add `docker/Dockerfile.fact_check`.
- Update `docker-compose.yml` to include `fact-check-service`.
- Reduce OCR model config to det + rec only.
- Add embedding model path config.
- Add `data/knowledge_db/`, `data/source_data/`, and `data/fact_check/`.

Deliverable:

```text
The repository starts with 4 services and clean config, even if fact-check logic is still stubbed.
```

## Phase 2 — Simplify `ocr-service`

Tasks:

- Replace OCR pipeline with det + rec only.
- Add `POST /v1/ocr/plain`.
- Return JSON with `text`, `lines`, `warnings`, and timing metadata.
- Remove Markdown/document pipeline from active code.
- Keep old pipeline archived if needed.

Deliverable:

```text
Screenshot/image input returns plain text.
```

## Phase 3 — Build local F1 knowledge database

Tasks:

- Import Formula 1 CSV files into SQLite.
- Generate `facts`.
- Download/use `all-MiniLM-L6-v2` from global model storage.
- Build FAISS index.
- Save `build_manifest.json`.
- Add inspection and smoke-test scripts.

Deliverable:

```text
Local SQLite + FAISS can retrieve known F1 facts.
```

## Phase 4 — Implement `fact-check-service`

Tasks:

- Add text, URL, and image preprocessing.
- Add OCR client.
- Add LLM client.
- Add retrieval module.
- Add claim classification module.
- Add Brave Search client.
- Add web article fetch and evidence ranking module.
- Add verdict generation module.
- Add response aggregation.
- Add stable API schemas.

Deliverable:

```text
POST /v1/check works for text, URL, and image.
```

## Phase 5 — Refactor `llm-service`

Tasks:

- Keep llama-server startup and health logic.
- Add structured JSON task support.
- Add claim extraction request handling.
- Add verdict generation request handling.
- Add JSON validation and retry logic.

Deliverable:

```text
The service reliably returns schema-compatible claim and verdict JSON.
```

## Phase 6 — Refactor `web-app`

Tasks:

- Replace OCR assistant UI text and layout.
- Add text/URL/image input tabs.
- Replace quick action button with `Check F1 News`.
- Remove OCR result and copy button.
- Render the fact-check result sections.
- Update session history to show fact-check runs.

Deliverable:

```text
The browser app behaves as an F1 fact-checking product.
```

## Phase 7 — End-to-end validation

Minimum smoke tests:

```text
[1] Text input:
"Max Verstappen won the 2021 Abu Dhabi Grand Prix."

[2] Text input with false claim:
"Lewis Hamilton won the 2021 Abu Dhabi Grand Prix."

[3] URL input:
A saved or live F1 article URL.

[4] Image input:
Screenshot of a short F1 news claim.

[5] Mixed article:
One supported claim, one refuted claim, one unverifiable claim.
```

Expected output:

```text
Fact-check result
├── Overall verdict
├── Extracted claims
├── Verdict for each claim
└── Explanation from Gemma based on local DB and/or web evidence
```

---

# Final Target Runtime Flow

```text
User opens web-app
↓
User submits text, URL, or screenshot
↓
web-app creates a session/check run
↓
web-app sends request to fact-check-service
↓
fact-check-service preprocesses input
    ├── text: normalize directly
    ├── url: fetch + extract main article
    └── image: call ocr-service for plain text
↓
fact-check-service calls llm-service to extract claims
↓
fact-check-service calls llm-service to classify claims
├── structured factual claims:
│   └── retrieve evidence from SQLite + FAISS
│
└── news / drama / statement claims:
    └── use Brave Search API, fetch top 3 articles, and rank web evidence
↓
fact-check-service calls llm-service for claim verdicts
↓
fact-check-service aggregates final verdict
↓
web-app renders:
    ├── Overall verdict
    ├── Extracted claims
    ├── Verdict for each claim
    └── Explanation from Gemma based on local DB and/or web evidence
```

## Recommended Rule for This Refactor

Treat OCR as an internal preprocessing utility, not the product.

The new product is the **F1 fact-checking workflow**. The clean architecture should make that visible in the repository structure, service names, API contracts, UI, and documentation.
