from __future__ import annotations

import asyncio
import importlib
import io
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class FakeOCRPipeline:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    def extract_text(self, image: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(image)
        return {
            "job_id": kwargs.get("job_id", "fake-job"),
            "text": "Max Verstappen wins the race.",
            "normalized_text": "max verstappen wins the race.",
            "lines": [
                {
                    "order": 1,
                    "text": "Max Verstappen wins the race.",
                    "normalized_text": "max verstappen wins the race.",
                    "bbox": [1, 2, 30, 12],
                    "confidence": 0.99,
                }
            ],
            "line_count": 1,
            "meta": {"engine": "fake", "fixture": "unit-test"},
        }


@pytest.fixture()
def ocr_main(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Any, FakeOCRPipeline]:
    monkeypatch.setenv("OCR_PRELOAD_PIPELINE_ON_STARTUP", "0")
    monkeypatch.setenv("OCR_WARMUP_ON_STARTUP", "0")
    monkeypatch.setenv("OCR_DATA_DIR", str(tmp_path))

    module = importlib.import_module("ocr_service.main")
    upload_dir = tmp_path / "uploads"
    result_dir = tmp_path / "ocr_text"
    upload_dir.mkdir(exist_ok=True)
    result_dir.mkdir(exist_ok=True)

    fake_pipeline = FakeOCRPipeline()
    monkeypatch.setattr(module, "UPLOAD_DIR", upload_dir, raising=False)
    monkeypatch.setattr(module, "RESULT_DIR", result_dir, raising=False)
    monkeypatch.setattr(module, "pipeline", None, raising=False)
    monkeypatch.setattr(module, "get_pipeline", lambda: fake_pipeline)
    return module, fake_pipeline


def upload_file(filename: str, content: bytes, content_type: str) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


def png_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
        b"\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01"
        b"\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def test_healthz_exposes_service_status(ocr_main: tuple[Any, FakeOCRPipeline]) -> None:
    module, _ = ocr_main

    payload = module.healthz()

    assert payload["status"] in {"ok", "starting"}
    assert "startup_ready" in payload
    assert "startup_error" in payload


def test_v1_ocr_accepts_image_upload_and_returns_json_contract(
    ocr_main: tuple[Any, FakeOCRPipeline],
) -> None:
    module, fake_pipeline = ocr_main

    result = asyncio.run(
        module.ocr_image(upload_file("sample.png", png_bytes(), "image/png"))
    )

    assert result.job_id
    assert result.text == "Max Verstappen wins the race."
    assert result.normalized_text == "max verstappen wins the race."
    assert result.lines[0].order == 1
    assert result.lines[0].bbox == [1, 2, 30, 12]
    assert result.line_count == 1
    assert result.meta == {"engine": "fake", "fixture": "unit-test"}
    assert len(fake_pipeline.calls) == 1


@pytest.mark.parametrize(
    ("filename", "content", "content_type"),
    [
        ("notes.txt", b"not an image", "text/plain"),
        ("document.pdf", b"%PDF-1.4\n%", "application/pdf"),
    ],
)
def test_v1_ocr_rejects_non_image_uploads(
    ocr_main: tuple[Any, FakeOCRPipeline],
    filename: str,
    content: bytes,
    content_type: str,
) -> None:
    module, fake_pipeline = ocr_main

    with pytest.raises(HTTPException) as context:
        asyncio.run(module.ocr_image(upload_file(filename, content, content_type)))

    assert context.value.status_code == 400
    assert "Only image uploads are supported" in str(context.value.detail)
    assert fake_pipeline.calls == []
