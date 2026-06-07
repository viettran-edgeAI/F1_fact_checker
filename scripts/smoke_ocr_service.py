#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def build_multipart(image_path: Path, field_name: str = "image") -> tuple[bytes, str]:
    boundary = f"----ocr-smoke-{uuid.uuid4().hex}"
    content_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    image_bytes = image_path.read_bytes()
    parts = [
        f"--{boundary}\r\n".encode(),
        (
            f'Content-Disposition: form-data; name="{field_name}"; '
            f'filename="{image_path.name}"\r\n'
        ).encode(),
        f"Content-Type: {content_type}\r\n\r\n".encode(),
        image_bytes,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def post_image(service_url: str, image_path: Path, timeout: float) -> tuple[int, str]:
    body, content_type = build_multipart(image_path)
    endpoint = service_url.rstrip("/") + "/v1/ocr"
    request = Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
        },
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        return response.status, response.read().decode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Post an image to a running OCR service.")
    parser.add_argument("image", type=Path, help="Path to a real image file.")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="OCR service base URL.")
    parser.add_argument("--timeout", type=float, default=30.0, help="Request timeout in seconds.")
    args = parser.parse_args()

    if not args.image.is_file():
        parser.error(f"image path does not exist or is not a file: {args.image}")

    try:
        status, body = post_image(args.url, args.image, args.timeout)
    except HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}", file=sys.stderr)
        return 1
    except URLError as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        return 1

    print(f"HTTP {status}")
    try:
        print(json.dumps(json.loads(body), indent=2, sort_keys=True))
    except json.JSONDecodeError:
        print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
