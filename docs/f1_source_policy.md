# F1 Source Policy / Whitelist Guide

This document explains how to use `configs/source_policy.yaml` in the F1 fact-checking project.

## Goal

The web route should not send raw Brave Search results directly to Gemma. It should first normalize, filter, and rank evidence sources.

The policy file is a **source trust policy**, not just a hard whitelist. It helps the fact-check service decide:

- which Brave results are highly trusted
- which sources should be kept only as weak context
- which sources should be ignored or downgraded
- how many evidence items should be passed to Gemma

## Recommended position in the pipeline

```text
claim
↓
query generation
↓
Brave LLM Context API
↓
normalize domains / URLs
↓
apply source_policy.yaml
↓
deduplicate and rank evidence
↓
compact evidence packet
↓
Gemma verdict per claim
```

## Source tiers

### `official`

Use this tier for official F1, FIA, championship, and team sources.

Best for:

- sporting regulations
- technical regulations
- penalties
- race calendar
- official race results
- team announcements
- official driver/team statements

Examples:

```text
fia.com
formula1.com
redbullracing.com
mclaren.com
cadillacf1team.com
```

### `major_news`

Use this tier for major news organizations.

Best for:

- breaking F1 news
- governance/business news
- confirmed driver/team announcements
- wider context around official statements

Examples:

```text
reuters.com
apnews.com
bbc.com
skysports.com
```

### `specialist_motorsport`

Use this tier for F1/motorsport outlets.

Best for:

- paddock news
- race weekend reporting
- technical analysis
- strategy analysis
- rumor context when clearly reported by reputable journalists

Examples:

```text
autosport.com
motorsport.com
the-race.com
racefans.net
```

### `stats_reference`

Use this tier for historical or statistical cross-checking.

Best for:

- historical results
- driver/team statistics
- old records

Prefer the local structured database first when possible.

### `social_forum`

Use this tier only as weak context.

Do not allow a strong verdict based only on social/forum/video sources.

Examples:

```text
reddit.com
x.com
youtube.com
instagram.com
```

### `unknown`

Any unmatched domain falls into this tier.

Unknown sources can be useful when a claim is obscure, but they should be downgraded and should not produce a strong verdict unless confirmed by better sources.

## Suggested Brave limits

The YAML file uses compact defaults for a local Gemma/Jetson setup:

```yaml
maximum_number_of_urls: 5
maximum_number_of_snippets: 12
maximum_number_of_tokens: 3000
maximum_number_of_tokens_per_url: 800
```

This avoids sending too much noisy context into the local LLM.

For a heavier server, these values can be increased. For Jetson Orin Nano, keep them conservative.

## Verdict policy by claim type

The policy file includes claim-specific source rules.

### Regulation / penalty claims

Use strong verdict only when supported by official sources, preferably FIA or Formula 1.

If only blogs, forums, or social posts are found, return:

```text
insufficient_reliable_evidence
```

### Race result / calendar claims

Prefer the local knowledge database first. If using web evidence, prefer official F1/FIA or trusted statistics references.

### Team / driver statement claims

Prefer official team pages, Formula 1, FIA, Reuters, BBC, Sky Sports, or other major/specialist outlets.

### Rumor / drama claims

Do not treat social media as confirmation. If the claim only appears in social/forum sources, use:

```text
unverified_rumor
```

### Technical analysis claims

Specialist motorsport sources are acceptable, but official sources should override them when there is a conflict.

## Evidence object shape

After applying the source policy, normalize each result into a compact object before sending to Gemma:

When compacting evidence, prefer readable article text over title-only snippets. The current fact-check flow allows longer snippets and falls back to `item.text` / `meta.text` when `snippet` is empty so article-body content survives into the final packet.

```json
{
  "claim_id": "claim_001",
  "route": "web",
  "query": "FIA 2026 F1 power unit regulation",
  "evidence": [
    {
      "title": "Example article title",
      "url": "https://example.com/article",
      "domain": "example.com",
      "source_tier": "official",
      "published_at": "2026-06-12",
      "score": 0.91,
      "snippet": "Relevant extracted text..."
    }
  ]
}
```

## Minimal implementation logic

```text
for each Brave result:
  normalize URL
  extract domain
  match domain against source_policy.yaml
  assign source_tier and trust_score
  discard blocked domains
  deduplicate by canonical URL
  limit sources per domain
  compute final_score
  keep top evidence items
```

Recommended scoring:

```text
final_score =
  0.45 * source_trust
+ 0.30 * semantic_relevance
+ 0.15 * recency
+ 0.10 * content_quality
```

## Maintenance rules

Review this policy when:

- a new F1 season starts
- a team changes name or official domain
- Brave logs show repeated low-quality domains
- a good source is repeatedly downgraded as `unknown`
- an SEO/spam domain appears often

Recommended update flow:

```text
logs from web route
↓
inspect unknown/low-quality domains
↓
add good domains to the right tier
↓
add spam domains to blocked_domains
↓
rerun web-route tests
```

## Important design rule

Do not let Gemma decide source trust from raw URLs alone.

The service should compute source tier and pass it explicitly into the prompt:

```text
Source tier: official
Source: fia.com
URL: ...
Text: ...
```

This keeps verdict generation more stable and easier to debug.
