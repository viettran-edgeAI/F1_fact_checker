# F1 Fact Checker

Formula 1 fact-checking stack for Jetson Orin Nano Super.

The repository is organized around four runtime services:

- `ocr-service`: image-to-text extraction for screenshots
- `llm-service`: Gemma/llama-server wrapper for prompt-driven reasoning
- `fact-check-service`: claim extraction, routing, retrieval, and verdict generation
- `web-app`: user-facing UI, auth/session handling, and fact-check history

## Quick Start

1. Read the directory structure doc: [docs/project_directory_structure.md](docs/project_directory_structure.md)
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
```mermaid
flowchart TD
    A["User input"] --> B{"Input type?"}

    B -->|Text| C["Normalize text"]
    B -->|Image / Screenshot| D["OCR service<br/>PP-OCRv5 det + rec"]
    B -->|URL| E["URL fetch / article extraction<br/>or Brave-assisted fetch"]

    D --> C
    E --> C

    C --> F["Clean text<br/>remove noise, boilerplate, OCR artifacts"]

    F --> G["Gemma: F1 relevance classification"]

    G -->|Not F1 related| H["Return early response"]
    H --> H1["Message:<br/>This content is not related to Formula 1.<br/>No fact-check was performed."]

    G -->|F1 related| I["Gemma: extract checkable claims"]

    I --> J{"Any checkable claims?"}

    J -->|No| K["Return:<br/>F1-related content found,<br/>but no checkable claim detected"]

    J -->|Yes| L["Gemma: classify each claim"]

    L --> M{"Claim route?"}

    M -->|Structured F1 fact| N["Local Knowledge DB<br/>SQLite + FAISS"]
    M -->|News / statement / rumor / drama| O["Internet Search<br/>Brave Search API"]

    N --> P["Evidence items"]
    O --> P

    P --> Q["Gemma: verdict generation"]
    Q --> R["Final fact-check result"]
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
