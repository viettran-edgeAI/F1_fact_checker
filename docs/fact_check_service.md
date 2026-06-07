# Fact-Check Service

## Purpose

`fact-check-service` is the orchestration layer for Formula 1 claim verification. It receives cleaned text, classifies whether the content is F1-related, extracts checkable claims, routes each claim to the correct evidence source, and returns claim-level and final verdicts.

This block is the center of the current F1 pipeline:

- structured factual claims are checked against the local Formula 1 knowledge database with SQLite/FTS retrieval
- news, drama, statement, and rumor-style claims are checked with Brave Search and fetched web evidence
- unsupported claims are returned with an explainable `NOT_ENOUGH_INFO` outcome

## Runtime Role

The service is a FastAPI app with a narrow HTTP surface. The currently active endpoints are:

- `GET /healthz`
- `GET /v1/knowledge/status`
- `POST /v1/knowledge/search`
- `POST /v1/check/text`

The text flow is:

1. normalize and classify the input for F1 relevance
2. return early if the input is not Formula 1 related
3. extract checkable claims from F1-related text
4. return early if no checkable claim is found
5. classify each claim into `structured`, `web`, `mixed`, or `unsupported`
6. retrieve evidence from the local knowledge database and/or Brave Search
7. generate claim verdicts with Gemma
8. aggregate the final verdict and response metadata

The current implementation is text-first. URL and image entry points are handled earlier in the product stack, but they are not part of the active `fact-check-service` HTTP contract yet.

## Input Contract

`POST /v1/check/text` accepts a `TextCheckRequest` with:

- `text`: required input text
- `max_claims`: maximum claims to extract
- `top_k`: maximum structured evidence rows to retrieve
- `verification_streams`: enabled routing targets
- `include_evidence`: whether to include evidence in the response
- `meta`: request metadata passed through to the result

## Routing Model

The service uses a two-stream verification model:

- `structured` claims go to the local SQLite knowledge database with FTS-backed retrieval support
- `web` claims go to Brave Search, then article fetch/ranking, then Gemma verdict generation
- `mixed` claims use both evidence paths
- `unsupported` claims skip retrieval and return `NOT_ENOUGH_INFO`

This is driven by:

- `llm_client.py` for relevance, extraction, classification, search-query generation, and verdict generation
- `retrieval.py` for local fact lookup against the SQLite knowledge base
- `web_search.py` for Brave Search API access
- `web_evidence.py` for article fetching and evidence ranking

## Response Shape

The main response model is `FinalCheckResponse`.

It returns:

- the original text
- the overall verdict
- per-claim verdicts
- unsupported claims
- a summary string
- runtime metadata such as run id, timing, warnings, and F1 relevance classification

Each claim verdict records:

- the extracted and classified claim
- the verdict label
- the verification stream used
- the evidence items used to support the verdict
- the `verified_by` source marker in metadata

The service also has explicit early-return responses for:

- content that is not related to Formula 1
- F1-related content with no checkable claim

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
- `JOLPICA_CACHE_DIR`
- `JOLPICA_BASE_URL`
- `JOLPICA_TIMEOUT_SECONDS`
- `LLM_SERVICE_URL`
- `FACT_LLM_TIMEOUT_SECONDS`
- `BRAVE_SEARCH_ENDPOINT`
- `BRAVE_NEWS_ENDPOINT`
- `BRAVE_SEARCH_COUNT`
- `BRAVE_SEARCH_TIMEOUT`
- `BRAVE_SEARCH_API_KEY`
- `FACT_CHECK_HOST`
- `FACT_CHECK_PORT`

## Limitations

- The service currently exposes text fact checking only.
- URL and image verification are planned elsewhere in the stack, not as active `fact-check-service` routes.
- Web evidence quality depends on Brave Search coverage and article accessibility.
- Verdict quality depends on model adherence to the claim and evidence prompts.

## Pipeline Fit

`fact-check-service` is the decision layer between input normalization and final verdict generation. It is designed to consume cleaned text from OCR, URL extraction, or direct text input, but only the text path is active in the current service API.
