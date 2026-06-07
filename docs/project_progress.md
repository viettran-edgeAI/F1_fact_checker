# Project Progress

Date: 2026-06-08

## Current Status

The repository refactor is substantially complete. The remaining work is integration hardening and endpoint expansion, not baseline structure.

## Completed

- OCR service is now image-only and returns structured text output.
- Local Formula 1 knowledge database build and Jolpica sync are in place.
- Hybrid claim routing is implemented in `fact-check-service` for structured vs web evidence.
- F1 relevance gating and early-return handling are implemented for non-F1 and non-checkable text.
- The public web app has been restructured around the fact-check flow.
- The documentation set has been rebuilt around the current four-service architecture.

## In Progress / Remaining

- Add `fact-check-service` URL and image endpoints if those input modes become part of the backend contract.
- Continue end-to-end smoke testing across web app, OCR, LLM, fact-check, and Brave integration.
- Harden web evidence extraction and ranking for more edge cases.
- Keep the knowledge database build and sync flow reproducible.

## Current Direction

The project is now centered on Formula 1 fact checking instead of OCR assistant behavior. The next steps are mostly about finishing the remaining input paths, improving reliability, and keeping the docs aligned with the live code.
