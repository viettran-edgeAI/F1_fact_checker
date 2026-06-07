# Project Overview

This repository is the F1 fact-checking stack refactored from the old OCR assistant codebase. The active system is centered on four services:

- `ocr-service`: image-to-text extraction for screenshots
- `llm-service`: Gemma/llama-server wrapper for prompt-driven reasoning tasks
- `fact-check-service`: claim routing, evidence retrieval, and verdict generation
- `web-app`: user-facing UI, auth/session layer, and fact-check session history

## How The Stack Fits Together

```text
User input
-> web-app
-> OCR service for images
-> fact-check-service
-> local knowledge DB and Brave Search
-> llm-service for extraction, classification, and verdict generation
-> final verdict shown back in web-app
```

The current fact-check pipeline is:

1. input is normalized into text
2. Gemma checks whether the content is Formula 1 related
3. Gemma extracts checkable claims
4. Gemma classifies each claim
5. structured claims use the local knowledge database
6. news / drama / statement claims use Brave Search and fetched web evidence
7. Gemma generates claim verdicts
8. the service aggregates a final verdict

## Directory Structure

| Path | Purpose |
| --- | --- |
| `/` | Root landing page, compose wiring, and runtime helpers. |
| `README.md` | Short project landing page and doc index. |
| `configs/` | Runtime config files and examples. |
| `data/` | Local runtime data, generated artifacts, caches, and knowledge DB output. |
| `docker/` | Service Dockerfiles. |
| `docs/` | Active documentation only. |
| `requirements/` | Python dependency sets split by service. |
| `scripts/` | Local helper scripts and database build/sync utilities. |
| `src/ocr_service/` | OCR image-to-text service. |
| `src/llm_service/` | LLM wrapper service. |
| `src/fact_check_service/` | Fact-check orchestration service. |
| `src/web_app/` | Public UI and session management service. |
| `tests/` | Automated tests for the current stack. |
| `third_party/` | Bundled third-party runtime dependencies. |
| `wheels/` | Jetson-compatible wheel cache. |
| `docker-compose.yml` | Local multi-service runtime definition. |
| `start_app.sh` / `stop_app.sh` | Shell helpers for bringing the stack up and down. |

## Component Docs

- [OCR service](ocr_service.md)
- [LLM service](llm_service.md)
- [Fact-check service](fact_check_service.md)
- [Web app](web_app.md)
- [Progress update](project_progress.md)

## Runtime Data

Important generated locations:

- `data/uploads/`: OCR upload staging
- `data/ocr_text/`: OCR plain-text outputs
- `data/knowledge_db/`: SQLite knowledge database and metadata
- `data/source_data/`: raw dataset downloads and Jolpica cache
- `data/fact_check/`: fact-check session artifacts and results
- `data/web_app/`: web-app session state and runtime files

## Notes

- Model files live outside the repository under `/home/viettran_orin/models`.
- Secrets belong in the project-root `.env`, not in committed config files.
- Old OCR assistant documentation has been removed from the active docs set.
