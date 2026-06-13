from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from typing import Any
from urllib import error, request


class FactCheckServiceError(RuntimeError):
    pass


class FactCheckClient:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def check_text(self, text: str, *, meta: dict[str, object] | None = None) -> dict[str, Any]:
        return self._post_json(
            "/v1/check/text",
            {
                "text": text,
                "meta": meta or {},
            },
        )

    def stream_check_text(self, text: str, *, meta: dict[str, object] | None = None) -> Iterator[dict[str, Any]]:
        return self._post_json_stream(
            "/v1/check/text/stream",
            {
                "text": text,
                "meta": meta or {},
            },
        )

    def check_url(self, url: str, *, meta: dict[str, object] | None = None) -> dict[str, Any]:
        return self._post_json(
            "/v1/check/url",
            {
                "url": url,
                "meta": meta or {},
            },
        )

    def stream_check_url(self, url: str, *, meta: dict[str, object] | None = None) -> Iterator[dict[str, Any]]:
        return self._post_json_stream(
            "/v1/check/url/stream",
            {
                "url": url,
                "meta": meta or {},
            },
        )

    def check_image(
        self,
        *,
        filename: str,
        content_type: str,
        body: bytes,
        meta: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        boundary = f"----f1-fact-check-web-app-{uuid.uuid4().hex}"
        payload = self._multipart_body(
            filename=filename,
            content_type=content_type,
            body=body,
            boundary=boundary,
            meta=meta or {},
        )
        return self._send(
            "/v1/check/image",
            payload,
            {"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )

    def stream_check_image(
        self,
        *,
        filename: str,
        content_type: str,
        body: bytes,
        meta: dict[str, object] | None = None,
    ) -> Iterator[dict[str, Any]]:
        boundary = f"----f1-fact-check-web-app-{uuid.uuid4().hex}"
        payload = self._multipart_body(
            filename=filename,
            content_type=content_type,
            body=body,
            boundary=boundary,
            meta=meta or {},
        )
        return self._send_stream(
            "/v1/check/image/stream",
            payload,
            {"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )

    def _post_json(self, path: str, payload: dict[str, object]) -> dict[str, Any]:
        return self._send(
            path,
            json.dumps(payload).encode("utf-8"),
            {"Content-Type": "application/json"},
        )

    def _post_json_stream(self, path: str, payload: dict[str, object]) -> Iterator[dict[str, Any]]:
        return self._send_stream(
            path,
            json.dumps(payload).encode("utf-8"),
            {"Content-Type": "application/json"},
        )

    def _send(self, path: str, payload: bytes, headers: dict[str, str]) -> dict[str, Any]:
        req = request.Request(
            f"{self.base_url}{path}",
            data=payload,
            method="POST",
            headers=headers,
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise FactCheckServiceError(f"Fact-check service failed: {detail}") from exc
        except error.URLError as exc:
            raise FactCheckServiceError(f"Fact-check service is unavailable: {exc.reason}") from exc

        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise FactCheckServiceError("Fact-check service returned invalid JSON.") from exc
        if not isinstance(decoded, dict):
            raise FactCheckServiceError("Fact-check service returned an unexpected payload.")
        return decoded

    def _send_stream(self, path: str, payload: bytes, headers: dict[str, str]) -> Iterator[dict[str, Any]]:
        req = request.Request(
            f"{self.base_url}{path}",
            data=payload,
            method="POST",
            headers={**headers, "Accept": "text/event-stream"},
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                yield from _iter_sse_events(response)
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise FactCheckServiceError(f"Fact-check service failed: {detail}") from exc
        except error.URLError as exc:
            raise FactCheckServiceError(f"Fact-check service is unavailable: {exc.reason}") from exc

    def _multipart_body(
        self,
        *,
        filename: str,
        content_type: str,
        body: bytes,
        boundary: str,
        meta: dict[str, object],
    ) -> bytes:
        parts = [
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
            + body
            + b"\r\n",
            (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="meta"\r\n'
                "Content-Type: application/json\r\n\r\n"
                f"{json.dumps(meta)}\r\n"
            ).encode("utf-8"),
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
        return b"".join(parts)


def _iter_sse_events(response: Any) -> Iterator[dict[str, Any]]:
    event_name = "message"
    data_lines: list[str] = []
    for raw_line in response:
        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line:
            if data_lines:
                yield _decode_sse_event(event_name, data_lines)
            event_name = "message"
            data_lines = []
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip() or "message"
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        yield _decode_sse_event(event_name, data_lines)


def _decode_sse_event(event_name: str, data_lines: list[str]) -> dict[str, Any]:
    try:
        payload = json.loads("\n".join(data_lines))
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return {"event": event_name, "data": payload}
