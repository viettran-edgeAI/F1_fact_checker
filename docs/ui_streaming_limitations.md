# UI Streaming Status

Date: 2026-06-13

## Summary

The previous request/response-only UI limitation has been resolved. The browser now consumes the fact-check stream directly and renders backend stage events, live Gemma verdict tokens, and the final persisted result.

## Client-Side Progress Display

The progress line shown in the web UI is driven by backend stream events from `fact-check-service`, not by a browser-side timer.

The browser renders the real backend stage sequence as it arrives, so the visible progress now tracks the actual work in flight:

- claim extraction
- claim classification
- claim context completion (`claim_context_completion`)
- structured knowledge database retrieval
- Brave/web evidence retrieval
- Gemma verdict generation
- session/result persistence

## Live Verdict Tokens

Gemma verdict tokens now stream through the full stack during verdict generation.

The browser receives those tokens through the web-app SSE proxy and appends them as the final verdict is generated. This is live model output, not a reveal animation.

## Current Backend Behavior

The active fact-check flow is stream based:

```text
browser submits input
-> web-app creates/updates a session
-> web-app opens the SSE stream to fact-check-service
-> fact-check-service runs the full pipeline
-> fact-check-service streams backend stage events and verdict tokens
-> web-app proxies the stream and persists the final session detail
-> browser renders the streamed progress and final result
```

`llm-service` still provides the underlying streaming answer endpoint, and `fact-check-service` now uses it for streamed verdict generation.

## Compatibility

The blocking JSON endpoints remain available for compatibility and non-streaming consumers, but they are no longer the primary browser path.

## Notes

- The browser treats backend events as the source of truth for progress.
- Live token streaming is only enabled for the verdict-generation portion of the pipeline.
- The stored session detail remains the final canonical result rendered after `done`.
