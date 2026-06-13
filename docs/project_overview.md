# Project Overview

## Goal

This repository implements a local Formula 1 fact-checking stack for Jetson Orin Nano Super. The system accepts text, URLs, and screenshots, converts each input into normalized text, retrieves supporting evidence from local F1 data and selected web sources, and returns claim-level verdicts.

The project is organized around four runtime services:

- `web-app`: public browser UI, auth/session handling, and result persistence
- `fact-check-service`: claim extraction, routing, retrieval, and verdict generation
- `llm-service`: local Gemma/`llama-server` wrapper for prompt execution
- `ocr-service`: image-to-text extraction for screenshot inputs

## Current System Shape

The current product is an F1-specific fact checker, not a general OCR assistant.

The active verification model is:

1. normalize incoming text, URL content, or OCR output
2. extract Formula 1-related checkable claims
3. return early when no F1-related checkable claim is found
4. classify each claim into a retrieval route
5. rewrite and normalize structured-route claims before local retrieval when needed
6. execute structured retrieval, web retrieval, or both
7. generate per-claim verdicts from the evidence
8. stream backend stage events and live Gemma verdict tokens to the browser when the streaming endpoints are used
9. aggregate the final fact-check result for the UI or API caller

At a high level:

```text
user input
-> web-app or direct service call
-> OCR or URL normalization when needed
-> fact-check-service orchestration
-> local LLM prompts + local F1 knowledge retrieval + Brave-backed web evidence
-> final verdict response
```

## Main Modules

### `web-app`

The web app is the user-facing entry point. It serves the browser UI, manages guest and authenticated identities, stores session history in SQLite, saves uploaded screenshots and fact-check results, and forwards text, URL, and image requests to `fact-check-service`, including the live session stream used by the browser.

### `fact-check-service`

This is the center of the system. It owns:

- claim extraction
- claim classification
- route planning
- Gemma-based structured-claim rewrite / normalization before local retrieval
- structured retrieval from the local F1 knowledge base
- web retrieval through Brave search/context plus source-policy evidence ranking
- verdict generation and final response aggregation

It exposes the main blocking and streaming verification endpoints for text, URL, and image inputs.

### `llm-service`

This service wraps a local `llama-server` process running a Gemma GGUF model. It provides a small HTTP API for prompt execution and returns model answers plus timing, usage, and streaming metadata. It does not decide fact-check logic; it is the prompt execution backend used by `fact-check-service`.

### `ocr-service`

This service converts uploaded images into plain text using Paddle OCR. Its scope is intentionally narrow: image-only OCR for screenshot-based fact checking.

## Evidence Model

The project currently uses two evidence routes:

- `structured`: local F1 knowledge database backed by SQLite plus vector retrieval
- `web`: Brave `llm/context` grounding with optional article fetch, normalization, source-policy filtering, and ranking

Claims may use one route, both routes, or be marked unsupported when the system cannot retrieve reliable evidence.

## Knowledge Base

The local structured knowledge base is built from:

- Formula 1 World Championship dataset files under `data/F1_WC_data/`
- Jolpica sync/cache data under `data/source_data/jolpica_cache/`

The build flow converts structured rows into deterministic natural-language facts, stores them with metadata, generates embeddings, and supports both keyword and semantic retrieval for historical/statistical F1 claims.

## Repository Organization

The codebase follows a module-oriented layout:

- `src/` contains runtime services
- `tests/` contains service and pipeline tests
- `scripts/` contains build, sync, smoke-test, and inspection helpers
- `configs/` contains env examples and source policy configuration
- `docs/` contains active project and service documentation

For the exact tree, see [project_structure.md](/home/viettran_orin/Documents/F1_fact_checker/docs/project_structure.md).

## Runtime Assumptions

- Model files live outside the repository and are referenced through config env files.
- Deployment secrets belong in the root `.env`, not in committed config files.
- The local stack is designed to run as cooperating services through `docker-compose.yml` or equivalent direct service startup.

## Current Status

The repository refactor to the four-service F1 architecture is largely complete. The end-to-end path for text, URL, and image fact-checking exists, including SSE-backed live streaming through the browser, and the remaining work is mostly reliability hardening around retrieval quality, URL normalization, and broader integration validation.

For implementation status details, see [project_progress.md](/home/viettran_orin/Documents/F1_fact_checker/docs/project_progress.md).
