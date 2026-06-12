# F1 Fact Checker

Formula 1 fact-checking stack for Jetson Orin Nano Super.

The repository is organized around four runtime services:

- `ocr-service`: image-to-text extraction for screenshots
- `llm-service`: Gemma/llama-server wrapper for prompt-driven reasoning
- `fact-check-service`: claim extraction, routing, retrieval, and verdict generation
- `web-app`: user-facing UI, auth/session handling, and fact-check history

## Quick Start

1. Read the directory structure doc: [docs/project_structure.md](docs/project_structure.md)
2. Read the service docs for the blocks you care about:
   - [OCR service](docs/ocr_service.md)
   - [LLM service](docs/llm_service.md)
   - [Fact-check service](docs/fact_check_service.md)
   - [Web app](docs/web_app.md)
3. Check the current progress note: [docs/project_progress.md](docs/project_progress.md)

## Current Architecture

The current verification model extracts all checkable claims first, then executes
retrieval by route before consolidating evidence back into claim verdicts:

- structured factual claims use the local Formula 1 knowledge database with SQLite + FAISS-backed retrieval
- news / drama / statement claims use Brave `llm/context` grounding first, then optional article fetch, normalization, and ranking
- mixed claims require both structured and web routes

The current text flow is:
```text
input
↓
text normalization
↓
claim extraction
↓
claim classification per claim
↓
claim execution planning
↓
structured route phase
↓
web route phase with Brave llm/context + source policy
↓
claim evidence consolidation
↓
claim-level verdict
↓
aggregate final result
```

```mermaid
flowchart TD
    A[User input] --> B{Input type?}

    B -->|Text| C[Normalize text]
    B -->|Image / Screenshot| D[OCR service<br/>Image to plain text]
    B -->|URL| E[Fetch / extract article text]

    D --> C
    E --> C

    C --> F[Clean normalized text]

    F --> G[Gemma: extract checkable F1 claims - (instant)]

    G --> H{Any checkable claims?}

    H -->|No| I[Return<br/>No F1-related claim found]

    H -->|Yes| J[Gemma: classify each claim - (instant)]

    J --> K[Gemma: claim execution planning - (instant)]

    K --> L[Claim list with required routes]

    L --> M[Structured route phase<br/>SQLite exact / FTS + FAISS semantic]

    L --> N[Web route phase<br/>query generation -> Brave llm/context<br/>+ source_policy.yaml filtering/ranking]

    M --> O[Claim evidence consolidation]
    N --> O

    O --> P[Gemma: generate verdict per claim - (instant/thinking)]

    P --> Q[Claim-level verdict]

    Q --> R[Gemma: aggregate final result - (thinking)]

    R --> S[Final fact-check result<br/>Overall verdict + claim verdicts + evidence]
```

`fact-check-service` exposes text, URL, and image endpoints. URL and image
inputs are normalized into clean text first, then all three paths reuse the same
claim extraction, routing, retrieval, and verdict pipeline. If no F1-related
checkable claim is extracted, the service returns `No F1-related claim found`.

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
