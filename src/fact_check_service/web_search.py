from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse

import httpx


DEFAULT_BRAVE_SEARCH_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
DEFAULT_BRAVE_NEWS_ENDPOINT = "https://api.search.brave.com/res/v1/news/search"
DEFAULT_BRAVE_SEARCH_COUNT = 5
DEFAULT_BRAVE_SEARCH_TIMEOUT = 10.0

SearchKind = Literal["web", "news"]


class BraveSearchError(RuntimeError):
    """Raised when Brave Search is misconfigured or returns an unusable response."""


@dataclass(frozen=True, slots=True)
class BraveSearchConfig:
    search_endpoint: str
    news_endpoint: str
    count: int
    timeout_seconds: float
    api_key: str | None

    @classmethod
    def from_env(cls) -> "BraveSearchConfig":
        return cls(
            search_endpoint=os.environ.get("BRAVE_SEARCH_ENDPOINT", DEFAULT_BRAVE_SEARCH_ENDPOINT),
            news_endpoint=os.environ.get("BRAVE_NEWS_ENDPOINT", DEFAULT_BRAVE_NEWS_ENDPOINT),
            count=_read_positive_int("BRAVE_SEARCH_COUNT", DEFAULT_BRAVE_SEARCH_COUNT),
            timeout_seconds=_read_positive_float("BRAVE_SEARCH_TIMEOUT", DEFAULT_BRAVE_SEARCH_TIMEOUT),
            api_key=os.environ.get("BRAVE_SEARCH_API_KEY"),
        )

    def require_api_key(self) -> str:
        if not self.api_key or not self.api_key.strip():
            raise BraveSearchError(
                "BRAVE_SEARCH_API_KEY is required for Brave Search API requests."
            )
        return self.api_key.strip()

    def endpoint_for(self, kind: SearchKind) -> str:
        if kind not in ("web", "news"):
            raise BraveSearchError("Search kind must be 'web' or 'news'.")
        return self.news_endpoint if kind == "news" else self.search_endpoint


@dataclass(frozen=True, slots=True)
class WebSearchResult:
    title: str
    url: str
    description: str | None = None
    snippet: str | None = None
    source: str | None = None
    domain: str | None = None
    published_at: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


class BraveSearchClient:
    def __init__(self, config: BraveSearchConfig | None = None) -> None:
        self.config = config or BraveSearchConfig.from_env()

    def search(
        self,
        query: str,
        *,
        kind: SearchKind = "web",
        count: int | None = None,
        client: httpx.Client | None = None,
    ) -> list[dict[str, str | None]]:
        payload = self._request(query=query, kind=kind, count=count, client=client)
        return [result.to_dict() for result in _normalize_results(payload, kind=kind)]

    async def asearch(
        self,
        query: str,
        *,
        kind: SearchKind = "web",
        count: int | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> list[dict[str, str | None]]:
        payload = await self._arequest(query=query, kind=kind, count=count, client=client)
        return [result.to_dict() for result in _normalize_results(payload, kind=kind)]

    def _request(
        self,
        *,
        query: str,
        kind: SearchKind,
        count: int | None,
        client: httpx.Client | None,
    ) -> dict[str, Any]:
        request_args = self._build_request_args(query=query, kind=kind, count=count)
        if client is not None:
            return self._parse_response(client.get(**request_args))

        with httpx.Client(timeout=self.config.timeout_seconds) as owned_client:
            return self._parse_response(owned_client.get(**request_args))

    async def _arequest(
        self,
        *,
        query: str,
        kind: SearchKind,
        count: int | None,
        client: httpx.AsyncClient | None,
    ) -> dict[str, Any]:
        request_args = self._build_request_args(query=query, kind=kind, count=count)
        if client is not None:
            return self._parse_response(await client.get(**request_args))

        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as owned_client:
            return self._parse_response(await owned_client.get(**request_args))

    def _build_request_args(
        self, *, query: str, kind: SearchKind, count: int | None
    ) -> dict[str, Any]:
        normalized_query = query.strip()
        if not normalized_query:
            raise BraveSearchError("Search query must not be empty.")

        return {
            "url": self.config.endpoint_for(kind),
            "headers": {
                "Accept": "application/json",
                "X-Subscription-Token": self.config.require_api_key(),
            },
            "params": {
                "q": normalized_query,
                "count": _validate_count(count) if count is not None else self.config.count,
            },
        }

    @staticmethod
    def _parse_response(response: httpx.Response) -> dict[str, Any]:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            raise BraveSearchError(
                f"Brave Search API request failed with HTTP {status_code}."
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise BraveSearchError("Brave Search API returned invalid JSON.") from exc

        if not isinstance(payload, dict):
            raise BraveSearchError("Brave Search API returned an unexpected payload.")
        return payload


def search_web(
    query: str,
    *,
    count: int | None = None,
    client: httpx.Client | None = None,
    config: BraveSearchConfig | None = None,
) -> list[dict[str, str | None]]:
    return BraveSearchClient(config).search(query, kind="web", count=count, client=client)


def search_news(
    query: str,
    *,
    count: int | None = None,
    client: httpx.Client | None = None,
    config: BraveSearchConfig | None = None,
) -> list[dict[str, str | None]]:
    return BraveSearchClient(config).search(query, kind="news", count=count, client=client)


def _normalize_results(payload: dict[str, Any], *, kind: SearchKind) -> list[WebSearchResult]:
    raw_results = _extract_raw_results(payload, kind=kind)
    normalized: list[WebSearchResult] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue

        title = _clean_string(item.get("title"))
        url = _clean_string(item.get("url"))
        if not title or not url:
            continue

        description = _clean_string(item.get("description") or item.get("snippet"))
        domain = _extract_domain(item, url)
        normalized.append(
            WebSearchResult(
                title=title,
                url=url,
                description=description,
                snippet=description,
                source=_extract_source(item, domain),
                domain=domain,
                published_at=_extract_published_at(item),
            )
        )
    return normalized


def _extract_raw_results(payload: dict[str, Any], *, kind: SearchKind) -> list[Any]:
    direct_results = payload.get("results")
    if isinstance(direct_results, list):
        return direct_results

    container_key = "news" if kind == "news" else "web"
    nested_container = payload.get(container_key)
    if isinstance(nested_container, dict) and isinstance(nested_container.get("results"), list):
        return nested_container["results"]

    return []


def _extract_domain(item: dict[str, Any], url: str) -> str | None:
    meta_url = item.get("meta_url")
    if isinstance(meta_url, dict):
        hostname = _clean_string(meta_url.get("hostname") or meta_url.get("netloc"))
        if hostname:
            return hostname

    parsed_hostname = urlparse(url).hostname
    return parsed_hostname.removeprefix("www.") if parsed_hostname else None


def _extract_source(item: dict[str, Any], domain: str | None) -> str | None:
    source = item.get("source")
    if isinstance(source, dict):
        return _clean_string(source.get("name")) or domain
    return _clean_string(source) or domain


def _extract_published_at(item: dict[str, Any]) -> str | None:
    for key in ("published_at", "date", "page_age", "age"):
        value = _clean_string(item.get(key))
        if not value:
            continue
        if key == "age":
            return value
        return _normalize_datetime(value)
    return None


def _normalize_datetime(value: str) -> str:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return value


def _clean_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    cleaned = value.strip()
    return cleaned or None


def _read_positive_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise BraveSearchError(f"{name} must be an integer.") from exc
    if parsed < 1:
        raise BraveSearchError(f"{name} must be greater than zero.")
    return parsed


def _validate_count(count: int) -> int:
    if not isinstance(count, int):
        raise BraveSearchError("Search count must be an integer.")
    if count < 1:
        raise BraveSearchError("Search count must be greater than zero.")
    return count


def _read_positive_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise BraveSearchError(f"{name} must be a number.") from exc
    if parsed <= 0:
        raise BraveSearchError(f"{name} must be greater than zero.")
    return parsed
