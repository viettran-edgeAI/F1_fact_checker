from __future__ import annotations

import os
import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import httpx

from .source_policy import SourcePolicy, load_source_policy


BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
DEFAULT_USER_AGENT = "F1-fact-checker/0.1"
MAX_ARTICLE_CHARS = 12_000

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "have",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "was",
    "were",
    "with",
}


@dataclass(frozen=True, slots=True)
class WebEvidence:
    title: str
    url: str
    source: str
    text: str
    score: float
    source_tier: str = "unknown"
    published_at: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedSearchResult:
    title: str
    url: str
    snippet: str
    source: str
    published_at: str | None = None
    source_tier: str = "unknown"
    source_trust: float = 0.45


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._hidden_tags: list[str] = []
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg", "template"}:
            self._hidden_tags.append(tag.lower())

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._hidden_tags and self._hidden_tags[-1] == tag:
            self._hidden_tags.pop()

    def handle_data(self, data: str) -> None:
        if not self._hidden_tags:
            text = " ".join(data.split())
            if text:
                self._chunks.append(text)

    def text(self) -> str:
        return " ".join(self._chunks)


def fetch_top_article_texts(
    query: str,
    *,
    brave_api_key: str | None = None,
    client: httpx.Client | None = None,
    max_results: int = 8,
    top_n: int = 3,
    timeout_seconds: float = 10.0,
) -> list[WebEvidence]:
    """Fetch Brave web results, download article pages, and return the top evidence texts.

    Tests should pass an httpx.Client with a MockTransport to avoid real network calls.
    Without an API key this returns an empty list instead of raising.
    """

    query = query.strip()
    api_key = brave_api_key or os.environ.get("BRAVE_API_KEY")
    if not query or not api_key or max_results <= 0 or top_n <= 0:
        return []

    owns_client = client is None
    http_client = client or httpx.Client(timeout=timeout_seconds, follow_redirects=True)
    try:
        results = _brave_results(http_client, query, api_key, max_results, timeout_seconds)
        evidence = [
            evidence
            for index, result in enumerate(results)
            if (evidence := _article_evidence(http_client, query, result, index, timeout_seconds))
        ]
    finally:
        if owns_client:
            http_client.close()

    return sorted(evidence, key=lambda item: item.score, reverse=True)[:top_n]


def fetch_web_evidence(
    query: str,
    *,
    brave_api_key: str | None = None,
    client: httpx.Client | None = None,
    max_results: int = 8,
    top_n: int = 3,
    timeout_seconds: float = 10.0,
) -> list[WebEvidence]:
    return fetch_top_article_texts(
        query,
        brave_api_key=brave_api_key,
        client=client,
        max_results=max_results,
        top_n=top_n,
        timeout_seconds=timeout_seconds,
    )


def fetch_ranked_evidence_from_results(
    query: str,
    results: list[dict[str, Any]],
    *,
    client: httpx.Client | None = None,
    top_n: int = 3,
    timeout_seconds: float = 10.0,
) -> list[WebEvidence]:
    query = query.strip()
    if not query or not results or top_n <= 0:
        return []

    owns_client = client is None
    http_client = client or httpx.Client(timeout=timeout_seconds, follow_redirects=True)
    try:
        evidence = [
            evidence
            for index, result in enumerate(results)
            if (evidence := _article_evidence(http_client, query, _normalize_result(result), index, timeout_seconds))
        ]
    finally:
        if owns_client:
            http_client.close()

    return sorted(evidence, key=lambda item: item.score, reverse=True)[:top_n]


def normalize_search_results(
    results: list[dict[str, Any]],
    *,
    source_policy: SourcePolicy | None = None,
) -> list[NormalizedSearchResult]:
    policy = source_policy or load_source_policy()
    normalized_results: list[NormalizedSearchResult] = []
    for result in results:
        normalized = _normalize_result(result)
        title = _clean_text(str(normalized.get("title") or ""))
        url = str(normalized.get("url") or "").strip()
        if not title or not url.startswith(("http://", "https://")):
            continue
        hostname = _hostname(url)
        if policy.is_blocked(hostname):
            continue
        tier = policy.tier_for_domain(hostname)
        normalized_results.append(
            NormalizedSearchResult(
                title=title,
                url=url,
                snippet=_clean_text(str(normalized.get("description") or "")),
                source=hostname,
                published_at=str(normalized.get("published_at") or "") or None,
                source_tier=tier.name,
                source_trust=tier.trust_score,
            )
        )
    return normalized_results


def fetch_article_texts(
    results: list[NormalizedSearchResult],
    *,
    client: httpx.Client | None = None,
    timeout_seconds: float = 10.0,
) -> dict[str, str]:
    if not results:
        return {}

    owns_client = client is None
    http_client = client or httpx.Client(timeout=timeout_seconds, follow_redirects=True)
    try:
        texts = {
            result.url: _fetch_article_text(http_client, result.url, timeout_seconds)
            for result in results
        }
    finally:
        if owns_client:
            http_client.close()
    return {url: text for url, text in texts.items() if text}


def rank_evidence_candidates(
    query: str,
    results: list[NormalizedSearchResult],
    article_texts: dict[str, str],
    *,
    top_n: int = 3,
    source_policy: SourcePolicy | None = None,
) -> list[WebEvidence]:
    policy = source_policy or load_source_policy()
    ranked: list[WebEvidence] = []
    for index, result in enumerate(results):
        text = article_texts.get(result.url) or result.snippet
        if not text:
            continue
        ranked.append(
            WebEvidence(
                title=result.title,
                url=result.url,
                source=result.source,
                text=text,
                score=rank_article(
                    query,
                    title=result.title,
                    url=result.url,
                    snippet=result.snippet,
                    text=text,
                    result_index=index,
                    source_policy=policy,
                    published_at=result.published_at,
                ),
                source_tier=result.source_tier,
                published_at=result.published_at,
            )
        )
    return sorted(ranked, key=lambda item: item.score, reverse=True)[:top_n]


def extract_visible_text(html: str, *, max_chars: int = MAX_ARTICLE_CHARS) -> str:
    if not html:
        return ""

    try:
        parser = _VisibleTextParser()
        parser.feed(html)
        text = parser.text()
    except Exception:
        text = _strip_tags(html)

    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars].strip()


def rank_article(
    query: str,
    *,
    title: str,
    url: str,
    snippet: str = "",
    text: str = "",
    result_index: int = 0,
    source_policy: SourcePolicy | None = None,
    published_at: str | None = None,
) -> float:
    query_terms = _tokenize(query)
    if not query_terms:
        return 0.0

    policy = source_policy or load_source_policy()
    weighted_text = f"{title} {title} {snippet} {snippet} {text[:3000]}"
    article_terms = set(_tokenize(weighted_text))
    semantic_relevance = len(query_terms & article_terms) / max(len(query_terms), 1)
    source_trust = policy.tier_for_url(url).trust_score
    recency = _recency_score(published_at)
    content_quality = min(len(text) / 2500.0, 1.0)
    position_bonus = max(0.0, 0.05 - (result_index * 0.005))

    score = (
        source_trust * policy.weight("source_trust", 0.45)
        + semantic_relevance * policy.weight("semantic_relevance", 0.30)
        + recency * policy.weight("recency", 0.15)
        + content_quality * policy.weight("content_quality", 0.10)
        + position_bonus
    )
    return round(score, 4)


def _brave_results(
    client: httpx.Client,
    query: str,
    api_key: str,
    max_results: int,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    try:
        response = client.get(
            BRAVE_SEARCH_URL,
            params={"q": query, "count": min(max_results, 20), "safesearch": "moderate"},
            headers={
                "Accept": "application/json",
                "User-Agent": DEFAULT_USER_AGENT,
                "X-Subscription-Token": api_key,
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return []

    raw_results = payload.get("web", {}).get("results", [])
    if not isinstance(raw_results, list):
        return []
    return [result for result in raw_results[:max_results] if isinstance(result, dict)]


def _article_evidence(
    client: httpx.Client,
    query: str,
    result: dict[str, Any],
    result_index: int,
    timeout_seconds: float,
) -> WebEvidence | None:
    url = str(result.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return None

    title = _clean_text(str(result.get("title") or ""))
    snippet = _clean_text(str(result.get("description") or ""))
    text = _fetch_article_text(client, url, timeout_seconds)
    if not text:
        text = snippet
    if not text:
        return None

    score = rank_article(query, title=title, url=url, snippet=snippet, text=text, result_index=result_index)
    tier = load_source_policy().tier_for_url(url)
    return WebEvidence(title=title, url=url, source=_hostname(url), text=text, score=score, source_tier=tier.name)


def _normalize_result(result: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(result)
    if "description" not in normalized and "snippet" in normalized:
        normalized["description"] = normalized.get("snippet")
    return normalized


def _fetch_article_text(client: httpx.Client, url: str, timeout_seconds: float) -> str:
    try:
        response = client.get(
            url,
            headers={"Accept": "text/html,*/*", "User-Agent": DEFAULT_USER_AGENT},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return ""

    content_type = response.headers.get("content-type", "")
    if "html" not in content_type and "<html" not in response.text[:500].lower():
        return ""
    return extract_visible_text(response.text)


def _hostname(url: str) -> str:
    hostname = urlparse(url).hostname or ""
    return hostname.lower().removeprefix("www.")


def _recency_score(published_at: str | None) -> float:
    if not published_at:
        return 0.5
    year_match = re.search(r"\b(20\d{2}|19\d{2})\b", published_at)
    if not year_match:
        return 0.5
    year = int(year_match.group(1))
    if year >= 2025:
        return 1.0
    if year >= 2022:
        return 0.8
    if year >= 2010:
        return 0.6
    return 0.4


def _tokenize(value: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", value.lower())
    return {token for token in tokens if len(token) > 2 and token not in STOPWORDS}


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(_strip_tags(value))).strip()


def _strip_tags(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    return re.sub(r"(?s)<[^>]+>", " ", value)
