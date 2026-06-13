# Web App

`web_app` is the public browser UI and session layer for the F1 fact-checking system. It runs the user-facing FastAPI app on port `8080`, handles identity and session state, and forwards fact-check requests to `fact-check-service`.

## Purpose

The web app is responsible for:

- presenting the F1 fact-check UI in the browser
- managing guest and authenticated identities
- creating and persisting fact-check sessions
- sending text, URL, and image inputs to `fact-check-service`, including live session streams
- rendering the returned verdict, claim list, evidence summary, and debug payload

It does not perform OCR, claim extraction, retrieval, or verdict generation itself.

## Runtime Role

The current UI is fact-check specific. It exposes:

- text fact-check submission
- URL fact-check submission
- image/screenshot upload for fact-checking
- recent session browsing
- session open/delete/bulk-delete
- auth flows for login, signup, logout, and account inspection
- theme toggle and help modal

The legacy OCR assistant UI is no longer part of the active surface.

## Identity And Sessions

The app resolves an `Identity` for every request:

- authenticated users come from the signed auth cookie
- guests get a signed guest cookie on first use

That identity is the ownership boundary for:

- session rows in SQLite
- uploaded screenshots
- persisted fact-check result JSON
- recent-session listings
- rate-limit accounting

Session ownership is tracked as `owner_type` and `owner_id`, not as a global shared workspace.

## Fact-Check Submission Flow

The UI has three submission modes:

- `text` streams through `POST /sessions/check/stream`
- `url` streams through `POST /sessions/check/stream`
- `image` streams through `POST /sessions/check-image/stream`

The legacy blocking `POST /sessions/check` and `POST /sessions/check-image` endpoints remain available for compatibility.

High-level flow:

1. The user enters text, pastes a URL, or uploads a screenshot.
2. The web app validates the input and generates or reuses a `session_id`.
3. A session row is created or updated with preprocessing state and a short input preview.
4. The app opens the SSE stream to `fact-check-service`, proxies backend stage events, `gemma_token` events, `done`, and `error` back to the browser, and keeps the session row in sync.
5. The `done` event carries the serialized session detail, which is persisted locally and rendered back into the session view.

For image submissions, the uploaded file is also written to disk before the backend call.

## What It Persists

The web app stores session state in `WEB_APP_DATA_DIR/sessions.sqlite3` and writes artifacts under the same base directory.

Persisted items include:

- session metadata
- auth and account state
- rate-limit events
- fact-check run records
- per-claim verdict rows
- the raw result JSON returned by `fact-check-service`
- uploaded image files for screenshot runs

Relevant artifact locations:

- `WEB_APP_DATA_DIR/uploads/...` for uploaded screenshots
- `WEB_APP_DATA_DIR/fact_check_results/...` for saved result JSON

The session history view is filtered to fact-check sessions only.

## Rendering

The browser UI renders the streamed result under a `Fact checking system` header in a chatbot-like layout. The browser uses fetch-based SSE parsing, renders backend stage events as they arrive, shows live Gemma verdict tokens during generation, and then replaces the live view with the final persisted session detail when `done` arrives.

The rendered result includes:

- claim validity
- source
- explanation
- conclusion
- optional debug payload

The interaction shell keeps fixed input/output panel heights and uses backend-driven progress instead of timer-based status guesses.

Opening a session restores the saved input state for that session before rendering the stored result immediately.

Claim evidence is collapsed by default when multiple evidence items exist: the top evidence item remains visible, and the user can expand the evidence box to see up to four evidence items for that claim.

Recent sessions are rendered from the SQLite-backed session list. The list items no longer show the generated filename/header, displayed input text is capped in the browser, and the status and delete controls stay fixed on the right.

## Service Boundary

`web_app` talks to `fact-check-service` through `FactCheckClient`:

- `POST /v1/check/text/stream` for text input
- `POST /v1/check/url/stream` for URL input
- `POST /v1/check/image/stream` for image input

The blocking JSON endpoints remain available for compatibility. The web app does not inspect claim evidence or decide verdicts. It only forwards the user input, streams backend events, and stores the final session detail.

## Configuration

Relevant environment variables:

- `WEB_APP_DATA_DIR` for SQLite and artifact storage
- `FACT_CHECK_SERVICE_URL` for the backend service base URL
- `WEB_APP_SECRET_KEY` for signed auth and guest cookies
- `WEB_APP_COOKIE_SECURE` to mark cookies secure in deployment
- `WEB_APP_KNOWLEDGE_SOURCE_LABEL` to customize the local knowledge-source label shown in claim evidence
- `WEB_APP_SMTP_*` for email verification during signup

`WEB_APP_OWNER_EMAIL` is used to mark the owner account tier when configured.

## Notes

- The UI title, copy, and action labels are all fact-check oriented.
- The public session list is limited to fact-check runs, not legacy OCR/chat history.
- Legacy OCR assistant behavior is disabled from the user-facing product flow.
