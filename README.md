# F1 Fact Checker

Local Formula 1 news fact-checking system for Jetson Orin Nano Super.

This repository is being refactored from a completed OCR AI assistant into an F1 fact-checking stack. The retained foundation includes Docker Compose wiring, a private OCR service, a private LLM service, local model mounts, runtime data storage, and the public web-app shell.

## Target Architecture

- `web-app`: public browser UI and session layer.
- `fact-check-service`: central orchestration service for text, URL, and image inputs.
- `ocr-service`: private image-to-text backend for screenshots only.
- `llm-service`: private Gemma/llama wrapper for claim extraction and verdict generation.

## Current Refactor Status

Step 1 is in progress/completed for the backend foundation:

- OCR service now exposes image-only plain-text extraction at `POST /v1/ocr`.
- Old OCR AI service docs have been moved to `docs/archive/jetson_ocr_ai/`.
- Initial `fact-check-service` scaffold and knowledge DB folders have been added.
- Active model config now keeps OCR detection/recognition, LLM, and embedding paths only.

See `docs/RESTRUCTURING_PROGRESS.md` for the latest restructuring notes.

## Model Configuration

Runtime model files are stored outside the repo in `/home/viettran_orin/models`.

- `configs/models.host.env` points local host runs to that model root.
- `configs/models.container.env` points Docker services to the same model root mounted at `/models`.
