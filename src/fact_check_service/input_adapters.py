from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import FactCheckConfig
from .schemas import CheckInputType, TextCheckRequest, URLCheckRequest
from .web_evidence import DEFAULT_USER_AGENT, extract_visible_text


@dataclass(frozen=True, slots=True)
class AdapterText:
    text: str
    meta: dict[str, object]


class InputAdapterError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def text_request_from_url(request: URLCheckRequest, adapter_text: AdapterText) -> TextCheckRequest:
    meta = dict(request.meta)
    meta["source_url"] = request.url
    meta["url_metadata"] = adapter_text.meta
    return TextCheckRequest(
        text=adapter_text.text,
        input_type=CheckInputType.URL,
        max_claims=request.max_claims,
        top_k=request.top_k,
        verification_streams=request.verification_streams,
        include_evidence=request.include_evidence,
        meta=meta,
    )


def text_request_from_image(
    *,
    text: str,
    meta: dict[str, object],
    options: TextCheckRequest | None = None,
) -> TextCheckRequest:
    source = options or TextCheckRequest(text=text)
    request_meta = dict(source.meta)
    request_meta["ocr_metadata"] = meta
    return TextCheckRequest(
        text=text,
        input_type=CheckInputType.IMAGE,
        max_claims=source.max_claims,
        top_k=source.top_k,
        verification_streams=source.verification_streams,
        include_evidence=source.include_evidence,
        meta=request_meta,
    )


def fetch_url_text(
    url: str,
    *,
    config: FactCheckConfig,
    client: httpx.Client | None = None,
) -> AdapterText:
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in config.url_allowed_schemes:
        allowed = ", ".join(config.url_allowed_schemes)
        raise InputAdapterError(f"URL scheme must be one of: {allowed}.")
    if not parsed.netloc:
        raise InputAdapterError("URL must include a host.")

    owns_client = client is None
    http_client = client or httpx.Client(timeout=config.url_fetch_timeout_seconds, follow_redirects=True)
    try:
        try:
            response = http_client.get(
                url,
                headers={"Accept": "text/html,text/plain,*/*", "User-Agent": DEFAULT_USER_AGENT},
                timeout=config.url_fetch_timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise InputAdapterError(
                f"URL fetch failed with HTTP {exc.response.status_code}.",
                status_code=502,
            ) from exc
        except httpx.HTTPError as exc:
            raise InputAdapterError(f"URL fetch failed: {exc}", status_code=502) from exc
    finally:
        if owns_client:
            http_client.close()

    raw = response.content[: config.url_fetch_max_bytes]
    encoding = response.encoding or "utf-8"
    html_or_text = raw.decode(encoding, errors="replace")
    content_type = response.headers.get("content-type", "")
    if "html" in content_type.lower() or "<html" in html_or_text[:500].lower():
        text = extract_visible_text(html_or_text)
    else:
        text = html_or_text

    cleaned = clean_normalized_text(text)
    if not cleaned:
        raise InputAdapterError("URL did not contain readable text.", status_code=422)

    return AdapterText(
        text=cleaned,
        meta={
            "source_url": str(response.url),
            "content_type": content_type,
            "bytes_read": len(raw),
            "truncated": len(response.content) > config.url_fetch_max_bytes,
        },
    )


def ocr_image_text(
    *,
    filename: str,
    content_type: str,
    body: bytes,
    config: FactCheckConfig,
    client: httpx.Client | None = None,
) -> AdapterText:
    if not content_type.startswith("image/"):
        raise InputAdapterError("Only image uploads are supported.")
    if not body:
        raise InputAdapterError("Image upload is empty.")

    owns_client = client is None
    http_client = client or httpx.Client(timeout=config.llm_timeout_seconds)
    try:
        try:
            response = http_client.post(
                f"{config.ocr_service_url}/v1/ocr",
                files={"image": (filename or "upload.png", body, content_type)},
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise InputAdapterError(
                f"OCR service failed with HTTP {exc.response.status_code}.",
                status_code=502,
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise InputAdapterError(f"OCR service failed: {exc}", status_code=502) from exc
    finally:
        if owns_client:
            http_client.close()

    if not isinstance(payload, dict):
        raise InputAdapterError("OCR service returned an unexpected payload.", status_code=502)

    text = clean_normalized_text(str(payload.get("normalized_text") or payload.get("text") or ""))
    if not text:
        raise InputAdapterError("OCR did not detect readable text.", status_code=422)

    return AdapterText(
        text=text,
        meta={
            "job_id": payload.get("job_id"),
            "line_count": payload.get("line_count"),
            "ocr_meta": payload.get("meta") if isinstance(payload.get("meta"), dict) else {},
        },
    )


def parse_multipart_meta(value: str | None) -> dict[str, object]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise InputAdapterError("Image metadata must be valid JSON.") from exc
    if not isinstance(payload, dict):
        raise InputAdapterError("Image metadata must be a JSON object.")
    return {str(key): item for key, item in payload.items()}


def clean_normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
