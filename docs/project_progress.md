# Project Progress

Date: 2026-06-08

## Current Status

The repository refactor is substantially complete. The application now has an end-to-end path for text, URL, and image fact-checking, including staged multi-claim and multi-route orchestration. The remaining work is integration hardening around retrieval quality, URL normalization, and broader end-to-end validation.

## Completed

- OCR service is now image-only and returns structured text output.
- Local Formula 1 knowledge database build and Jolpica sync are in place.
- Multi-claim route planning is implemented in `fact-check-service` for structured, web, mixed, and unsupported claims.
- Claim extraction now acts as the F1 filter by extracting only Formula 1-related checkable claims.
- URL and image endpoints now normalize inputs into clean text and reuse the same extraction-driven early return.
- Structured retrieval now combines SQLite lookup with FAISS/vector search support.
- Web retrieval now runs as explicit sub-stages: query generation, Brave `llm/context` grounding, optional article fetch, evidence normalization, source-policy filtering, and ranking.
- The public web app has been restructured around the fact-check flow.
- The documentation set has been rebuilt around the current four-service architecture.

## README Flowchart Alignment

The current implementation covers the main pipeline represented in the README flowchart:

- user input enters through text, URL, or image paths
- image input is sent to `ocr-service` and normalized into clean text
- URL input is fetched and converted into visible text
- all input paths reuse `fact-check-service.check_normalized_text`
- Gemma extracts F1-related checkable claims directly
- text with no F1-related checkable claim returns `No F1-related claim found`
- extracted claims are classified into `structured`, `web`, `mixed`, or `unsupported`
- claim plans derive `required_routes` internally
- structured claims retrieve local SQLite + FAISS evidence
- web claims use Brave `llm/context` grounding plus optional fetched/ranked article evidence filtered by `configs/source_policy.yaml`
- mixed claims execute both route phases and consolidate evidence back per claim
- Gemma generates verdicts from the retrieved evidence
- the service aggregates claim verdicts into the final fact-check response

The implementation is therefore functionally complete for the major flow, but not every reliability improvement in the README vision is finished yet.

## Known Gaps Against README

- The README says URL handling is `URL fetch / article extraction or Brave-assisted fetch`; the current URL adapter performs direct URL fetch plus visible-text extraction. It does not use Brave-assisted URL discovery or fallback.
- The README clean-text step says noise, boilerplate, and OCR artifacts are removed; the current adapters perform basic visible-text extraction and whitespace cleanup, not robust boilerplate or OCR-artifact removal.

## In Progress / Remaining

- Continue end-to-end smoke testing across web app, OCR, LLM, fact-check, and Brave integration.
- Add Brave-assisted URL fetch fallback if the README behavior should remain the target.
- Improve clean-text normalization for URL boilerplate and OCR artifacts.
- Harden web evidence extraction and ranking for more edge cases.
- Keep the knowledge database build and sync flow reproducible.

## Current Direction

The project is now centered on Formula 1 fact checking instead of OCR assistant behavior. The next steps are mostly about finishing the remaining input paths, improving reliability, and keeping the docs aligned with the live code.
