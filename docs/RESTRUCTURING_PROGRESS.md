# F1 Fact Checker Restructuring Progress

## Step 1: Directory Cleanup and OCR Service Refactor

Date: 2026-06-07

Completed:

- Added the initial `src/fact_check_service/` package with a health-checkable FastAPI entry point.
- Added the planned knowledge and runtime storage folders under `src/fact_check_service/knowledge/`, `data/fact_check/`, `data/knowledge_db/`, and `data/source_data/`.
- Added `docker/Dockerfile.fact_check`, `requirements/fact_check.txt`, and `configs/fact_check.env.example`.
- Renamed the OCR container build file to `docker/Dockerfile.ocr`.
- Archived old OCR AI service documents under `docs/archive/jetson_ocr_ai/`.
- Simplified OCR model config to active text detection and recognition model paths only.
- Changed OCR service `/v1/ocr` from document/PDF Markdown output to image-only JSON text extraction.
- Added a pytest API test for the new OCR service contract using a fake pipeline, so it does not require real PaddleOCR models.

Current OCR service contract:

```text
GET /healthz
POST /v1/ocr
```

`POST /v1/ocr` accepts image uploads only and returns:

```json
{
  "job_id": "string",
  "text": "plain OCR text",
  "normalized_text": "normalized OCR text",
  "lines": [],
  "line_count": 0,
  "meta": {}
}
```

Deferred to later steps:

- Full `fact-check-service` orchestration, claim extraction, retrieval, and verdict generation.
- Web UI replacement from OCR assistant to F1 fact-checking interface.
- Knowledge database import/sync scripts for Formula 1 CSV data and Jolpica.
- Final removal or archival of old OCR benchmarking/debug scripts and historical runtime artifacts.

## Step 2: Local F1 Knowledge Database Build

Date: 2026-06-07

Completed:

- Implemented SQLite schema for core Formula 1 tables, source metadata, aliases, generated facts, and an FTS5 fact index.
- Implemented CSV import from `data/F1_WC_data/`.
- Implemented deterministic fact generation for race locations, winners, finishes, podiums, pole positions, and season champions.
- Implemented Jolpica sync with response caching under `data/source_data/jolpica_cache/`.
- Added CLI scripts:
  - `scripts/build_f1_database.py`
  - `scripts/sync_jolpica.py`
  - `scripts/inspect_fact.py`
- Added fact-check service endpoints:
  - `GET /v1/knowledge/status`
  - `POST /v1/knowledge/search`
- Built `data/knowledge_db/f1.sqlite` from the downloaded dataset and synced 2025 data from Jolpica.

Current database status after build and 2025 sync:

```text
season_min: 1950
season_max: 2025
races: 1149
drivers: 864
constructors: 212
results: 27238
qualifying: 10973
facts: 34822
```

Validated retrieval example:

```text
Query: Verstappen won Abu Dhabi 2021
Top fact: Max Verstappen won the 2021 Abu Dhabi Grand Prix for Red Bull.
```

Deferred to later steps:

- FAISS vector index build with `all-MiniLM-L6-v2`.
- Claim extraction and verdict generation with the LLM service.
- End-to-end fact-check orchestration for text, URL, and image inputs.
