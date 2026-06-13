# Project Progress

Date: 2026-06-13

## Current Status

The repository refactor is substantially complete. The application now has an end-to-end path for text, URL, and image fact-checking, including staged multi-claim and multi-route orchestration plus real streaming from `fact-check-service` through `web-app` to the browser. The current live pipeline has been validated against the JSONL F1 fact-check case suite through Docker-backed `llm-service`, `fact-check-service`, OCR dependency startup, local DB retrieval, and Brave-backed web retrieval. The latest update added SSE-backed stage events, live Gemma verdict token streaming, serialized session persistence on `done`, claim context completion (`claim_context_completion`) before retrieval, updated no-F1 early-return wording, throughput metadata propagation, richer article-body evidence capture, and a refreshed browser result layout.

## Completed

- OCR service is now image-only and returns structured text output.
- Local Formula 1 knowledge database build and Jolpica sync are in place.
- Multi-claim route planning is implemented in `fact-check-service` for structured, web, mixed, and unsupported claims.
- Claim extraction now acts as the F1 filter by extracting only Formula 1-related checkable claims.
- Executable claims now pass through Gemma claim context completion before retrieval so standalone text can keep the source context needed by structured and web routes.
- URL and image endpoints now normalize inputs into clean text and reuse the same extraction-driven early return.
- Structured retrieval now combines SQLite lookup with FAISS/vector search support.
- Web retrieval now runs as explicit sub-stages: query generation, Brave `llm/context` grounding, article fetch for each normalized top candidate, evidence normalization, source-policy filtering, and ranking.
- The evidence packet now prefers readable article bodies when available and preserves Brave snippets as fallback ranking input.
- `fact-check-service` now exposes SSE `/stream` endpoints for text, URL, and image checks. They emit backend stage events, `gemma_token` verdict chunks, and terminal `done` / `error` events.
- `web-app` now proxies the streaming fact-check sessions through `/sessions/check/stream` and `/sessions/check-image/stream`, persists session updates, and returns the serialized session detail on `done`.
- The browser now uses fetch-based SSE parsing to render backend stage events, live Gemma verdict tokens, and the final persisted result.
- Docker Compose now mounts `configs/` into `fact-check-service` and sets `FACT_FAISS_INDEX_PATH` so the container loads the existing FAISS index instead of rebuilding vectors on first structured retrieval.
- Deterministic route and verdict safeguards are in place for stable local-DB patterns covered by the regression suite, including race winners, championship winners, driver title counts, driver/team/season checks, and known circuit facts.
- `llm-service` supports explicit request-level `enable_thinking` control and can report throughput metadata such as `tokens_per_second`; streamed `done` responses now carry the throughput value through the verdict path.
- Docker Compose now sets `LLM_CTX_SIZE=12288` for `llm-service` so verdict prompts can carry richer compacted web evidence.
- `fact-check-service` still uses non-thinking mode for extraction, classification, and query prompts, and keeps verdict JSON compact so final aggregation does not exhaust the context window.
- `fact-check-service` now returns `No information related to F1 could be extracted.` for responses with no F1-related checkable claim.
- `ocr-service` defaults now point to PP-OCRv6 small detection and recognition models.
- Docker Compose now keeps OCR on Paddle CUDA `gpu:0` and runs Gemma with llama.cpp CUDA offload (`LLM_GPU_LAYERS=8`) instead of CPU-only LLM inference.
- The browser UI now uses a chatbot-like `Fact checking system` result view, with claim validity/source/explanation/conclusion rows, backend-driven progress events, live verdict token streaming, fixed panel heights, and restored session input state.
- Recent session rows now omit the generated filename/header and keep status/delete controls fixed on the right.
- The public web app has been restructured around the fact-check flow.
- The documentation set has been rebuilt around the current four-service architecture.
- Live JSONL pipeline run completed with `27 pass, 0 warn, 0 fail, 0 error` using `tests/f1_fact_check_test_cases.jsonl`.

## README Flowchart Alignment

The current implementation covers the main pipeline represented in the README flowchart:

- user input enters through text, URL, or image paths
- image input is sent to `ocr-service` and normalized into clean text
- URL input is fetched and converted into visible text
- all input paths reuse `fact-check-service.check_normalized_text`
- Gemma extracts F1-related checkable claims directly
- text with no F1-related checkable claim returns `No information related to F1 could be extracted.`
- extracted claims are classified into `structured`, `web`, `mixed`, or `unsupported`
- claim plans derive `required_routes` internally
- executable claims pass through claim context completion after route planning and before structured or web retrieval
- structured and mixed claims refresh `structured_query` when the completed claim text changes
- web and mixed claims use the completed standalone claim text before search-query generation
- structured claims retrieve local SQLite + FAISS evidence
- web claims use Brave `llm/context` grounding plus optional fetched/ranked article evidence filtered by `configs/source_policy.yaml`
- mixed claims execute both route phases and consolidate evidence back per claim
- Gemma generates verdicts from the retrieved evidence
- the service streams backend stage events and live verdict tokens to the browser during the verdict phase
- the web app persists the final session detail and the browser renders that completed result

The implementation is therefore functionally complete for the major flow, but not every reliability improvement in the README vision is finished yet.

## Known Gaps Against README

- The README says URL handling is `URL fetch / article extraction or Brave-assisted fetch`; the current URL adapter performs direct URL fetch plus visible-text extraction. It does not use Brave-assisted URL discovery or fallback.
- The README clean-text step says noise, boilerplate, and OCR artifacts are removed; the current adapters perform basic visible-text extraction and whitespace cleanup, not robust boilerplate or OCR-artifact removal.

## In Progress / Remaining

- Continue end-to-end smoke testing across the streaming web app, OCR, LLM, fact-check, and Brave integration.
- Add Brave-assisted URL fetch fallback if the README behavior should remain the target.
- Improve clean-text normalization for URL boilerplate and OCR artifacts.
- Continue hardening web evidence extraction and ranking for more edge cases outside the current regression suite.
- Keep the knowledge database build and sync flow reproducible.

## Current Direction

The project is now centered on Formula 1 fact checking instead of OCR assistant behavior. The next steps are mostly about finishing the remaining input paths, improving reliability, and keeping the docs aligned with the live code.
