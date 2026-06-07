# F1 Fact Checker

Local Formula 1 news fact-checking system for Jetson Orin Nano Super.

This repository is being refactored from a completed OCR AI assistant into an F1 fact-checking stack. The retained foundation includes Docker Compose wiring, a private OCR service, a private LLM service, local model mounts, runtime data storage, and the public web-app shell.

## Target Architecture

- `web-app`: public browser UI and session layer.
- `fact-check-service`: central orchestration service for text, URL, and image inputs, including local DB retrieval and Brave Search web evidence.
- `ocr-service`: private image-to-text backend for screenshots only.
- `llm-service`: private Gemma/llama wrapper for claim extraction, claim classification, search-query generation, and verdict generation.

## Verification Model

Claims are split into two main types after Gemma extracts them:

- Structured factual claims are checked against the local Formula 1 knowledge database using SQLite and FAISS.
- News / drama / statement claims are checked with Brave Search API, fetched web articles, relevance/reliability ranking, and Gemma verdict generation.

Runtime flow:

```text
Input: text / URL / screenshot
↓
Preprocess input
↓
Gemma extracts checkable claims
↓
Gemma classifies each claim
├── Structured factual claim
│   └── Verify with local Knowledge Database: SQLite + FAISS
│
└── News / drama / statement claim
    └── Verify with Brave Search API + web evidence
↓
Gemma generates claim-level verdict
↓
Aggregate final verdict
```

Each claim result should clearly state whether it was verified by the local knowledge database, Brave Search web evidence, or both.

## Current Refactor Status

The backend foundation and public web-app refactor are now in progress/completed:

- OCR service now exposes image-only plain-text extraction at `POST /v1/ocr`.
- Old OCR AI service docs have been moved to `docs/archive/jetson_ocr_ai/`.
- Initial `fact-check-service` scaffold and knowledge DB folders have been added.
- Active model config now keeps OCR detection/recognition, LLM, and embedding paths only.
- `web-app` now presents the F1 Fact Checker product flow instead of the old OCR assistant UI.
- `web-app` supports text, URL, and image input modes and submits normal checks through `fact-check-service`.
- Fact-check sessions now persist run metadata, overall verdicts, claim verdicts, evidence JSON, and result JSON artifacts.
- Recent sessions are filtered to fact-check runs; legacy public OCR/chat endpoints are disabled with HTTP 410 responses.

Latest web-app verification:

- `rtk pytest -q` -> 26 passed.
- `rtk proxy pytest -q tests/test_web_app_fact_check.py` -> 4 passed.
- Tester subagent completed an independent web-app acceptance pass.

See `docs/RESTRUCTURING_PROGRESS.md` for the latest restructuring notes.

## Model Configuration

Runtime model files are stored outside the repo in `/home/viettran_orin/models`.

- `configs/models.host.env` points local host runs to that model root.
- `configs/models.container.env` points Docker services to the same model root mounted at `/models`.

## Secrets

Store deployment secrets in the project-root `.env`, not in committed config files. This includes:

- `WEB_APP_SECRET_KEY`
- SMTP credentials
- `BRAVE_SEARCH_API_KEY`
