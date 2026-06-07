# Web App

`web_app` is the public browser UI and session layer for the F1 fact-checking system. It runs the user-facing FastAPI app on port `8080`, handles identity and session state, and forwards fact-check requests to `fact-check-service`.

## Purpose

The web app is responsible for:

- presenting the F1 fact-check UI in the browser
- managing guest and authenticated identities
- creating and persisting fact-check sessions
- sending text, URL, and image inputs to `fact-check-service`
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

- `text` submits plain text to `POST /sessions/check`
- `url` submits a URL to `POST /sessions/check`
- `image` uploads a screenshot to `POST /sessions/check-image`

High-level flow:

1. The user enters text, pastes a URL, or uploads a screenshot.
2. The web app validates the input and generates or reuses a `session_id`.
3. A session row is created or updated with preprocessing state and a short input preview.
4. The app calls `fact-check-service`.
5. The returned fact-check result is persisted locally and rendered back into the session view.

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

The browser UI renders the returned result into three main areas:

- overall verdict
- extracted claims
- per-claim verdict cards
- final explanation
- optional debug payload

Recent sessions are rendered from the SQLite-backed session list. Opening a session reloads the stored detail view and latest fact-check result.

## Service Boundary

`web_app` talks to `fact-check-service` through `FactCheckClient`:

- `POST /v1/check/text` for text input
- `POST /v1/check/url` for URL input
- `POST /v1/check/image` for image input

The web app does not inspect claim evidence or decide verdicts. It only forwards the user input and stores the response.

## Configuration

Relevant environment variables:

- `WEB_APP_DATA_DIR` for SQLite and artifact storage
- `FACT_CHECK_SERVICE_URL` for the backend service base URL
- `WEB_APP_SECRET_KEY` for signed auth and guest cookies
- `WEB_APP_COOKIE_SECURE` to mark cookies secure in deployment
- `WEB_APP_SMTP_*` for email verification during signup

`WEB_APP_OWNER_EMAIL` is used to mark the owner account tier when configured.

## Notes

- The UI title, copy, and action labels are all fact-check oriented.
- The public session list is limited to fact-check runs, not legacy OCR/chat history.
- Legacy OCR assistant behavior is disabled from the user-facing product flow.
