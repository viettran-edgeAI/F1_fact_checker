# OCR Service

## Purpose

`ocr-service` is the private image-to-text backend used by the F1 fact-check pipeline. Its job is to turn a screenshot or other image upload into plain text that downstream services can normalize, classify, and verify.

Current scope is intentionally narrow:

- image-only OCR
- plain-text extraction for fact checking
- no document assistant, no PDF OCR, and no multi-step document processing flow

## Runtime Role

The service runs as a FastAPI app and exposes a minimal API for OCR and health checks. It uses Paddle OCR runtime components with PP-OCRv5 detection and recognition models:

- detection: `PP-OCRv5_mobile_det`
- recognition: `PP-OCRv5_mobile_rec`

The pipeline may optionally preload on startup and run a warmup inference using a synthetic image so the first real request does not pay the full initialization cost.

## API Contract

### `GET /healthz`

Returns a simple service readiness snapshot.

Response shape:

```json
{
  "status": "ok | starting",
  "startup_ready": true,
  "startup_error": null
}
```

`status` is `ok` only after startup work completes successfully. If startup fails, `startup_error` contains the exception string.

### `POST /v1/ocr`

Accepts a multipart form upload with one field:

- `image`: required file upload

Validation is strict:

- only `image/*` content types are accepted
- non-image uploads return HTTP 400

Response model: `OCRTextResponse`

High-level response shape:

```json
{
  "job_id": "string",
  "text": "raw extracted text",
  "normalized_text": "cleaned extracted text",
  "lines": [
    {
      "order": 1,
      "text": "line text",
      "normalized_text": "normalized line text",
      "confidence": 0.99,
      "bbox": [x1, y1, x2, y2]
    }
  ],
  "line_count": 1,
  "meta": {
    "original_filename": "optional filename",
    "content_type": "image/png",
    "image_size": [width, height],
    "profile": "fast | full",
    "device": "optional device",
    "engine": "paddle_static",
    "timings_ms": {}
  }
}
```

The service also writes the uploaded image to `data/uploads/` and the extracted normalized text to `data/ocr_text/` using a generated job id.

## Configuration Notes

Relevant runtime knobs:

- `OCR_DATA_DIR`: base directory for uploads and extracted text output; defaults to `<repo>/data`
- `OCR_PRELOAD_PIPELINE_ON_STARTUP`: pre-initialize the OCR pipeline; defaults to enabled
- `OCR_WARMUP_ON_STARTUP`: run a synthetic warmup inference during startup; defaults to enabled
- `OCR_HOST`: bind host when running the service directly; defaults to `0.0.0.0`
- `OCR_PORT`: bind port when running the service directly; defaults to `8000`

Model directories default under `~/models/ocr/` unless overridden by the OCR runtime config environment variables.

## Limitations

- Only image input is supported.
- The service does not perform claim extraction, F1 relevance classification, or fact verification.
- It does not handle PDF ingestion or document-layout assistant behavior.
- Output quality depends on the underlying OCR model and the visual quality of the input image.

## Pipeline Fit

`ocr-service` is only the first stage for screenshot-based fact checking:

1. `web-app` or another client sends an image to `POST /v1/ocr`
2. `ocr-service` returns extracted text
3. `fact-check-service` cleans and classifies that text
4. `llm-service` and the knowledge/web retrieval stack perform verification

In the current F1 stack, this service is a private dependency, not a user-facing product surface.
