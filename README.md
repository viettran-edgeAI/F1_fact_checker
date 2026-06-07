# F1 Fact Checker

Formula 1 fact-checking stack for Jetson Orin Nano Super.

The repository is organized around four runtime services:

- `ocr-service`: image-to-text extraction for screenshots
- `llm-service`: Gemma/llama-server wrapper for prompt-driven reasoning
- `fact-check-service`: claim extraction, routing, retrieval, and verdict generation
- `web-app`: user-facing UI, auth/session handling, and fact-check history

## Quick Start

1. Read the project overview: [docs/project_overview.md](docs/project_overview.md)
2. Read the service docs for the blocks you care about:
   - [OCR service](docs/ocr_service.md)
   - [LLM service](docs/llm_service.md)
   - [Fact-check service](docs/fact_check_service.md)
   - [Web app](docs/web_app.md)
3. Check the current progress note: [docs/project_progress.md](docs/project_progress.md)

## Current Architecture

The current verification model splits claims into two classes after Gemma processing:

- structured factual claims use the local Formula 1 knowledge database
- news / drama / statement claims use Brave Search and fetched web evidence

The current text flow is:

```text
User input
-> normalize and clean text
-> Gemma F1 relevance classification
-> early return if not F1 related
-> Gemma claim extraction
-> early return if no checkable claim exists
-> Gemma claim classification
-> structured/local or web evidence retrieval
-> Gemma verdict generation
-> final fact-check response
```

## Model Storage

Runtime model files live outside the repository under `/home/viettran_orin/models`.

- `configs/models.host.env` points local host runs to that model root
- `configs/models.container.env` points Docker services to the same mounted model root

## Secrets

Store deployment secrets in the project-root `.env`, not in committed config files. This includes:

- `WEB_APP_SECRET_KEY`
- SMTP credentials
- `BRAVE_SEARCH_API_KEY`

## Documentation Policy

Active documentation lives in `docs/` plus this root `README.md`. Legacy OCR-era docs are no longer part of the active documentation set.
