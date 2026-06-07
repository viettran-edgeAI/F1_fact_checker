# F1 Fact-Checking System: Hybrid Knowledge and Web Evidence Design

## Overview

The system should use a hybrid verification design.

Structured Formula 1 facts should be verified against the local knowledge database:

```text
Formula 1 World Championship Dataset
        +
Jolpica F1 API
        ↓
Local Knowledge Database
        ↓
SQLite + FAISS
↓
RAG with Gemma 4 E2B
```

News, drama, personal-life, and statement claims should be verified with live web evidence:

```text
Claim
        ↓
Gemma generates search query
        ↓
Brave Search API
        ↓
Fetch top 3 result articles
        ↓
Rank evidence by relevance and reliability
        ↓
Gemma compares claim with web evidence
```

The system should support three input types:

- Plain text
- Screenshot/image input
- URL input

Regardless of the input type, the system should always use Gemma 4 E2B to extract one or more checkable claims. Gemma should then classify each claim into one of two verification streams:

- Structured factual claim: race results, qualifying, standings, calendars, circuits, teams, drivers, championships, and other stable F1 records.
- News / drama / statement claim: public statements, rumors, controversies, penalties under discussion, contracts not yet represented in the local DB, personal-life claims, paddock drama, and recent news.

## 1. Role of Each Data Source

### 1.1. Formula 1 World Championship Dataset

This dataset should be used as the initial source for building the database.

Main roles:

- Provides historical Formula 1 data.
- Can run fully offline.
- Is easy to import from CSV files.
- Is suitable for a Jetson-based demo system.

Key files to use:

```text
drivers.csv
constructors.csv
circuits.csv
races.csv
results.csv
qualifying.csv
driver_standings.csv
constructor_standings.csv
```

### 1.2. Jolpica F1 API

Jolpica F1 API should be used as the update source for newer Formula 1 knowledge.

Main roles:

- Fetch seasons or races newer than the Kaggle dataset.
- Update new race results.
- Add new standings data.
- Resynchronize data when needed.

Jolpica should not be called directly during fact-checking. Instead, it should be used to update SQLite first, and the local database should be used during inference.

### 1.3. Brave Search API

Brave Search API should be used at runtime for claims that cannot be reliably answered from the structured Formula 1 database.

Main roles:

- Search the live web for news, drama, statements, interviews, and personal-life claims.
- Provide candidate evidence sources for recent or non-structured claims.
- Help verify claims that depend on article context rather than race-result tables.

Brave Search API belongs inside `fact-check-service`. The service should not expose Brave directly to the browser. `fact-check-service` should call Brave, fetch article text for the top results, rank evidence, and send the claim plus evidence to Gemma for the verdict.

The Brave API key should be stored in the project-root `.env` with other secrets, for example:

```bash
BRAVE_SEARCH_API_KEY=change-me
```

## 2. Database Build Pipeline

```text
[1] Load Kaggle CSV files
        ↓
[2] Normalize data
        ↓
[3] Import into SQLite
        ↓
[4] Sync new data from Jolpica F1 API
        ↓
[5] Upsert into SQLite
        ↓
[6] Generate fact_text
        ↓
[7] Encode fact_text with all-MiniLM-L6-v2
        ↓
[8] Build FAISS index
        ↓
[9] Use for RAG-based fact-checking
```

## 3. Local Database Structure

Recommended storage design:

```text
SQLite + FAISS
```

SQLite stores structured data:

- `drivers`
- `constructors`
- `circuits`
- `races`
- `results`
- `qualifying`
- `driver_standings`
- `constructor_standings`
- `aliases`
- `sources`
- `facts`

FAISS stores vector embeddings for each `fact_text` entry.

## 4. Most Important Table: `facts`

After importing structured data, the system should generate short natural-language fact statements.

Examples:

- Max Verstappen won the 2021 Abu Dhabi Grand Prix.
- Lewis Hamilton finished P2 in the 2021 Abu Dhabi Grand Prix.
- Red Bull won the 2023 Constructors' Championship.
- Sebastian Vettel won the 2013 Drivers' Championship.
- The 2021 Abu Dhabi Grand Prix was held at Yas Marina Circuit.

Suggested schema:

| Field | Meaning |
|---|---|
| `fact_id` | Unique fact ID |
| `fact_text` | Natural-language fact used for retrieval |
| `subject` | Fact subject, such as driver, team, or race |
| `relation` | Relationship, such as won, finished, or held_at |
| `object` | Fact object |
| `season` | F1 season |
| `race_id` | Race ID, if applicable |
| `driver_id` | Driver ID, if applicable |
| `constructor_id` | Constructor/team ID, if applicable |
| `source` | Data source |
| `updated_at` | Last update timestamp |

## 5. Updating Data with Jolpica

Sync workflow:

```text
[1] Check the latest season available in SQLite
[2] Call Jolpica API for missing seasons or the current season
[3] Fetch races, results, qualifying data, and standings
[4] Normalize driver, team, and circuit names
[5] Upsert into SQLite
[6] Regenerate fact_text for new data
[7] Encode new fact_text entries
[8] Update the FAISS index
```

Example:

```text
Local DB currently has data up to 2024
↓
Jolpica has 2025 data
↓
Fetch season 2025
↓
Upsert races/results/standings
↓
Generate 2025 facts
↓
Update FAISS
```

## 6. Role of `all-MiniLM-L6-v2`

`all-MiniLM-L6-v2` is used to generate embeddings for fact text.

```text
fact_text
↓
all-MiniLM-L6-v2
↓
384-dimensional embedding
↓
FAISS index
```

When a claim is submitted:

```text
Claim:
"Verstappen took victory in Abu Dhabi 2021."

FAISS retrieve:
"Max Verstappen won the 2021 Abu Dhabi Grand Prix."
```

This allows the system to match different phrasings of the same fact.

## 7. Input Processing and Claim Extraction

The fact-checking workflow should not directly verify the raw user input. It should first convert any input into normalized text, then use Gemma 4 E2B to extract checkable claims.

### 7.1. Supported Input Types

```text
User input
├── Plain text
├── Screenshot / image
└── URL
```

### 7.2. Plain Text Input

For plain text, the system can send the text directly to Gemma after lightweight cleaning.

Recommended steps:

```text
[1] Receive text input
[2] Normalize whitespace
[3] Remove obvious UI noise if present
[4] Send cleaned text to Gemma 4 E2B
[5] Extract checkable claims
```

Example input:

```text
Verstappen won the 2021 Abu Dhabi Grand Prix, while Hamilton finished second.
```

Expected extracted claims:

```json
[
  {
    "claim": "Max Verstappen won the 2021 Abu Dhabi Grand Prix.",
    "entities": {
      "driver": "Max Verstappen",
      "race": "Abu Dhabi Grand Prix",
      "season": 2021
    }
  },
  {
    "claim": "Lewis Hamilton finished second in the 2021 Abu Dhabi Grand Prix.",
    "entities": {
      "driver": "Lewis Hamilton",
      "race": "Abu Dhabi Grand Prix",
      "season": 2021,
      "position": 2
    }
  }
]
```

### 7.3. Screenshot or Image Input

For screenshot input, OCR should run before claim extraction.

Recommended steps:

```text
[1] Receive screenshot/image
[2] Run OCR pipeline
[3] Convert OCR result to Markdown or plain text
[4] Clean obvious OCR artifacts
[5] Send cleaned OCR text to Gemma 4 E2B
[6] Extract checkable claims
```

The OCR module should not decide the final verdict. Its role is only to recover readable text from the image.

### 7.4. URL Input

For URL input, the system should first fetch and clean the article content before claim extraction. This preprocessing step is important because web pages often contain navigation text, ads, cookie banners, comments, related articles, and other noisy content.

Recommended URL preprocessing pipeline:

```text
[1] Receive URL
[2] Validate URL format and scheme
[3] Fetch HTML content
[4] Extract the main article body
[5] Remove boilerplate content
[6] Normalize text
[7] Optionally keep metadata
[8] Send cleaned article text to Gemma 4 E2B
[9] Extract checkable claims
```

Detailed notes:

- URL validation should only allow `http` and `https` schemes.
- The fetcher should set a timeout and a maximum response size.
- The system should reject unsupported content types, such as binary downloads, unless a separate PDF/image path is implemented.
- Main-content extraction can use libraries such as `trafilatura`, `readability-lxml`, or a custom BeautifulSoup-based extractor.
- Boilerplate removal should remove headers, footers, menus, cookie banners, ads, comments, newsletter prompts, and related-article blocks.
- The cleaned article should preserve useful metadata when available, such as title, author, publication date, source domain, and canonical URL.
- If the page has too much text, chunk the article before sending it to Gemma.

Suggested URL extraction result:

```json
{
  "source_type": "url",
  "url": "https://example.com/f1-news",
  "title": "Example F1 Article Title",
  "published_at": "2025-04-10",
  "source_domain": "example.com",
  "clean_text": "Cleaned article body..."
}
```

## 8. Unified Fact-Checking Workflow

After preprocessing, all input types should follow the same verification flow.

```text
User input
↓
Input type?
├── Text → Normalize text
├── Image / Screenshot → OCR service with PP-OCRv5 det + rec → Normalize text
└── URL → URL fetch / article extraction or Brave-assisted fetch → Normalize text
↓
Clean text: remove noise, boilerplate, OCR artifacts
↓
Gemma: F1 relevance classification
├── Not F1 related
│   └── Return early response:
│       "This content is not related to Formula 1. No fact-check was performed."
│
└── F1 related
    ↓
    Gemma: extract checkable claims
    ↓
    Any checkable claims?
    ├── No
    │   └── Return:
    │       "F1-related content found, but no checkable claim detected."
    │
    └── Yes
        ↓
        Gemma: classify each claim
        ↓
        Claim route?
        ├── Structured F1 fact → Local Knowledge DB: SQLite + FAISS
        └── News / statement / rumor / drama → Internet Search: Brave Search API
        ↓
        Evidence items
        ↓
        Gemma: verdict generation
        ↓
        Final fact-check result
```

For a long article:

```text
Article text
↓
Gemma extracts multiple checkable claims
↓
Gemma classifies claims into structured and web-evidence streams
↓
Fact-check structured claims with local RAG
↓
Fact-check news/drama/statement claims with Brave Search and fetched web evidence
↓
Aggregate the final article-level verdict
```

### 8.1. Structured Factual Claim Stream

Use this stream for stable Formula 1 records.

```text
Claim
↓
Extract entities: driver, team, season, race, position, constructor, circuit
↓
Query SQLite when entities are clear
↓
Retrieve top-k facts with FAISS
↓
Merge and rank local evidence
↓
Gemma compares claim with local evidence
↓
Verdict: SUPPORTS / REFUTES / NOT_ENOUGH_INFO
```

### 8.2. News / Drama / Statement Claim Stream

Use this stream for claims about current news, public comments, rumors, controversies, contracts, personal lives, or paddock drama.

```text
Claim
↓
Generate search query with Gemma
↓
Brave Search API
↓
Fetch top n search results, default n=3
↓
Fetch full article text
↓
Rank evidence by relevance and reliability
↓
Gemma compares claim with web evidence
↓
Verdict: SUPPORTS / REFUTES / NOT_ENOUGH_INFO
```

Reliability ranking should prefer primary or high-quality sources:

- FIA, Formula 1, teams, drivers, race organizers, and official statements.
- Established motorsport outlets with named authors and publication dates.
- Articles that directly quote the relevant person or organization.
- Multiple independent sources over single-source rumor reporting.

The output must clearly state the verification source for each claim: local knowledge database, Brave Search web evidence, or both.

## 9. Recommended Gemma Claim Extraction Output

Gemma should return structured claim objects instead of free-form text.

Suggested format:

```json
[
  {
    "claim_id": "c001",
    "claim": "Max Verstappen won the 2021 Abu Dhabi Grand Prix.",
    "claim_type": "race_result",
    "verification_stream": "structured",
    "entities": {
      "driver": "Max Verstappen",
      "constructor": null,
      "race": "Abu Dhabi Grand Prix",
      "season": 2021,
      "position": 1,
      "circuit": null
    },
    "needs_fact_check": true
  }
]
```

Recommended claim types:

- `race_result`
- `qualifying_result`
- `driver_standing`
- `constructor_standing`
- `championship_result`
- `race_calendar`
- `circuit_info`
- `team_driver_relation`
- `statement`
- `contract_news`
- `controversy`
- `personal_life`
- `rumor`
- `breaking_news`
- `not_f1_claim`
- `unclear`

Recommended verification streams:

- `structured`
- `web`
- `not_f1_claim`
- `unclear`

## 10. Verdict Format

Each claim-level verdict should be stored in a structured format.

Suggested format:

```json
{
  "claim_id": "c001",
  "claim": "Max Verstappen won the 2021 Abu Dhabi Grand Prix.",
  "verdict": "SUPPORTS",
  "confidence": "high",
  "verification_stream": "structured",
  "verified_by": "local_knowledge_database",
  "evidence": [
    {
      "fact_id": "fact_2021_abudhabi_p1",
      "fact_text": "Max Verstappen won the 2021 Abu Dhabi Grand Prix.",
      "source": "Formula 1 World Championship Dataset"
    }
  ],
  "explanation": "The retrieved race result evidence states that Max Verstappen won the 2021 Abu Dhabi Grand Prix."
}
```

For a web-evidence claim:

```json
{
  "claim_id": "c002",
  "claim": "A driver publicly criticized his team after the race.",
  "verdict": "SUPPORTS",
  "confidence": "medium",
  "verification_stream": "web",
  "verified_by": "brave_search_web_evidence",
  "evidence": [
    {
      "title": "Example F1 news article",
      "url": "https://example.com/f1-news",
      "source_domain": "example.com",
      "published_at": "2026-05-20",
      "snippet": "Relevant paraphrased evidence from the article.",
      "reliability": "medium"
    }
  ],
  "explanation": "The web evidence includes a direct post-race quote that supports the claim."
}
```

Allowed verdict labels:

- `SUPPORTS`
- `REFUTES`
- `NOT_ENOUGH_INFO`

## 11. Important Design Rule

Gemma 4 E2B should be used in separate stages:

1. Claim extraction from the cleaned input.
2. Claim classification into structured factual claims or news/drama/statement claims.
3. Search-query generation for web-evidence claims.
4. Verdict generation from each claim plus retrieved local or web evidence.

The retrieval system should not depend on raw user text directly. This makes the system more robust across text input, screenshots, and URLs.
