# Fact-Check Service

## Purpose

`fact-check-service` is the orchestration layer for Formula 1 claim verification. It receives cleaned text, extracts Formula 1-related checkable claims, routes each claim to the correct evidence source, and returns claim-level and final verdicts.

This block is the center of the current F1 pipeline:

- structured factual claims are checked against the local Formula 1 knowledge database with SQLite exact / FTS plus FAISS semantic retrieval
- news, drama, statement, and rumor-style claims are checked with a staged web pipeline: query generation, Brave `llm/context` grounding, optional article fetch, evidence normalization, source-policy filtering, and ranking
- mixed claims require both structured and web evidence routes
- unsupported claims are returned with an explainable `NOT_ENOUGH_INFO` outcome

## Runtime Role

The service is a FastAPI app with a narrow HTTP surface. The currently active endpoints are:

- `GET /healthz`
- `GET /v1/knowledge/status`
- `POST /v1/knowledge/search`
- `POST /v1/check/text`
- `POST /v1/check/url`
- `POST /v1/check/image`

The normalized clean-text flow is:

1. normalize input text
2. extract Formula 1-related checkable claims
3. return early if no F1-related checkable claim is found
4. classify each claim and derive internal `required_routes`
5. build route worklists for structured and web execution
6. run the structured route phase for every claim that requires local evidence
7. run the web route phase for every claim that requires internet evidence
8. consolidate route evidence back into per-claim bundles
9. generate claim verdicts with Gemma
10. aggregate the final verdict and response metadata

The text, URL, and image endpoints all converge on the same normalized clean-text orchestration path. URL input is fetched and converted to visible text first. Image input is sent to `ocr-service`, then the returned normalized text uses the same claim extraction, routing, retrieval, and early-return behavior.

## Input Contract

`POST /v1/check/text` accepts a `TextCheckRequest` with:

- `text`: required input text
- `input_type`: normalized source marker; the text endpoint forces this to `text`
- `max_claims`: maximum claims to extract
- `top_k`: maximum structured evidence rows to retrieve
- `verification_streams`: enabled routing targets
- `include_evidence`: whether to include evidence in the response
- `meta`: request metadata passed through to the result

`POST /v1/check/url` accepts a `URLCheckRequest` with:

- `url`: required article/page URL
- `max_claims`, `top_k`, `verification_streams`, `include_evidence`, and `meta`

`POST /v1/check/image` accepts multipart form data with:

- `image`: required image upload
- `meta`: optional JSON object string passed through to the result

## Routing Model

The service uses `required_routes` as its internal routing source of truth:

- `structured` means the claim requires the structured route only
- `web` means the claim requires the web route only
- `mixed` is the compatibility label for claims that require both routes
- `unsupported` means the claim requires no retrieval routes and returns `NOT_ENOUGH_INFO`

The structured route executes:

- SQLite exact / keyword retrieval
- FAISS semantic retrieval
- result normalization and ranking

The web route executes:

- search-query generation
- Brave `llm/context` grounding
- optional article fetch
- evidence normalization
- source-policy filtering and evidence ranking

For Gemma-facing grounding, Brave `llm/context` is the primary source because it returns query-focused snippets already selected for LLM consumption. Full article fetch is used only when those snippets are missing or too thin to support a verdict.

Web evidence source trust is controlled by `configs/source_policy.yaml`. The policy assigns source tiers, blocks known low-quality domains, sets compact Brave LLM context defaults, and weights ranking by source trust, semantic relevance, recency, and content quality before evidence is passed to Gemma.

This is driven by:

- `llm_client.py` for extraction, classification, search-query generation, and verdict generation
- `input_adapters.py` for URL fetch/cleanup and OCR-service image normalization
- `orchestrator.py` for the reusable normalized-text flow and early-return handling
- `retrieval.py` for local fact lookup against the SQLite knowledge base
- `web_search.py` for Brave Search API access
- `source_policy.py` and `web_evidence.py` for article fetching, source-tier filtering, and evidence ranking

## Response Shape

The main response model is `FinalCheckResponse`.

It returns:

- the original text
- the overall verdict
- per-claim verdicts
- unsupported claims
- a summary string
- runtime metadata such as run id, timing, warnings, and inferred F1 claim-detection metadata

Each claim verdict records:

- the extracted and classified claim
- the verdict label
- the compatibility `verification_stream`
- the merged `evidence` list used by existing clients
- route-specific `structured_evidence` and `web_evidence`
- the `verified_by` source marker and route metadata

The service also has explicit early-return responses for:

- text with no F1-related checkable claim

## Knowledge Base

The local knowledge base is built from:

- `data/F1_WC_data/`
- Jolpica cached sync data under `data/source_data/jolpica_cache/`

The active SQLite database lives under `data/knowledge_db/f1.sqlite` unless overridden by config.

## Configuration Notes

Relevant environment variables:

- `FACT_DB_PATH`
- `FACT_SOURCE_DATA_DIR`
- `FACT_METADATA_PATH`
- `FACT_SOURCE_POLICY_PATH`
- `JOLPICA_CACHE_DIR`
- `JOLPICA_BASE_URL`
- `JOLPICA_TIMEOUT_SECONDS`
- `LLM_SERVICE_URL`
- `FACT_LLM_TIMEOUT_SECONDS`
- `BRAVE_SEARCH_ENDPOINT`
- `BRAVE_NEWS_ENDPOINT`
- `BRAVE_LLM_CONTEXT_ENDPOINT`
- `BRAVE_SEARCH_COUNT`
- `BRAVE_SEARCH_TIMEOUT`
- `BRAVE_CONTEXT_COUNT`
- `BRAVE_CONTEXT_MAX_URLS`
- `BRAVE_CONTEXT_MAX_SNIPPETS`
- `BRAVE_CONTEXT_MAX_TOKENS`
- `BRAVE_SEARCH_API_KEY`
- `OCR_SERVICE_URL`
- `URL_FETCH_TIMEOUT_SECONDS`
- `URL_FETCH_MAX_BYTES`
- `URL_ALLOWED_SCHEMES`
- `FACT_CHECK_HOST`
- `FACT_CHECK_PORT`

## Limitations

- URL extraction depends on page accessibility and readable HTML/text content.
- Image verification depends on `ocr-service` availability and OCR quality.
- Web evidence quality depends on Brave Search coverage and article accessibility.
- Verdict quality depends on model adherence to the claim and evidence prompts.

## Pipeline Fit

`fact-check-service` is the decision layer between input normalization and final verdict generation. Direct text enters the normalized-text flow immediately; URL and image endpoints normalize their sources first, then reuse the same claim extraction, routing, retrieval, and verdict generation path.
