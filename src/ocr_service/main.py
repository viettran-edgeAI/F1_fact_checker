from __future__ import annotations

import logging
import os
import shutil
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .pipeline import OCRPipeline
from .schemas import OCRTextResponse


APP_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("OCR_DATA_DIR", APP_ROOT / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
RESULT_DIR = DATA_DIR / "ocr_text"
WARMUP_IMAGE_PATH = DATA_DIR / ".ocr_warmup.png"

logger = logging.getLogger("ocr_service.main")

for path in (UPLOAD_DIR, RESULT_DIR):
    path.mkdir(parents=True, exist_ok=True)

pipeline: OCRPipeline | None = None
pipeline_lock = threading.Lock()
startup_ready = False
startup_error: str | None = None


def get_pipeline() -> OCRPipeline:
    global pipeline
    with pipeline_lock:
        if pipeline is None:
            logger.info("Initializing OCR pipeline...")
            pipeline = OCRPipeline()
            logger.info("OCR pipeline initialized.")
    return pipeline


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def warmup_pipeline(ocr: OCRPipeline) -> None:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (960, 480), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.text((48, 72), "OCR WARMUP 123", fill=(0, 0, 0))
    draw.text((48, 164), "F1 FACT CHECKER", fill=(0, 0, 0))
    image.save(WARMUP_IMAGE_PATH)
    try:
        ocr.extract_text(WARMUP_IMAGE_PATH, job_id="warmup", original_filename=WARMUP_IMAGE_PATH.name)
    finally:
        if WARMUP_IMAGE_PATH.exists():
            WARMUP_IMAGE_PATH.unlink(missing_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    del app
    global startup_ready, startup_error
    startup_ready = False
    startup_error = None

    preload = _env_bool("OCR_PRELOAD_PIPELINE_ON_STARTUP", True)
    warmup = _env_bool("OCR_WARMUP_ON_STARTUP", True)

    try:
        if preload:
            ocr = get_pipeline()
            if warmup:
                logger.info("Running OCR warm-up inference during startup...")
                warmup_pipeline(ocr)
                logger.info("OCR warm-up completed.")
        startup_ready = True
        logger.info(
            "OCR service startup complete (preload=%s, warmup=%s).",
            preload,
            warmup,
        )
    except Exception as exc:
        startup_error = str(exc)
        logger.exception("OCR service startup failed: %s", exc)
        raise

    yield


app = FastAPI(title="F1 Fact Checker OCR Service", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
def healthz() -> dict[str, str | bool | None]:
    return {
        "status": "ok" if startup_ready else "starting",
        "startup_ready": startup_ready,
        "startup_error": startup_error,
    }


@app.post("/v1/ocr", response_model=OCRTextResponse)
async def ocr_image(image: UploadFile = File(...)) -> OCRTextResponse:
    content_type = image.content_type or ""
    is_image = content_type.startswith("image/")
    if not is_image:
        raise HTTPException(status_code=400, detail="Only image uploads are supported.")

    job_id = uuid.uuid4().hex
    suffix = Path(image.filename or "upload").suffix or ".png"
    upload_path = UPLOAD_DIR / f"{job_id}{suffix}"
    result_path = RESULT_DIR / f"{job_id}.txt"

    with upload_path.open("wb") as buffer:
        shutil.copyfileobj(image.file, buffer)

    ocr = get_pipeline()
    result = OCRTextResponse.model_validate(
        ocr.extract_text(
            upload_path,
            job_id=job_id,
            original_filename=image.filename,
            content_type=image.content_type,
        )
    )

    result_path.write_text(result.normalized_text, encoding="utf-8")
    return result


def main() -> None:
    import uvicorn

    uvicorn.run(
        "ocr_service.main:app",
        host=os.environ.get("OCR_HOST", "0.0.0.0"),
        port=int(os.environ.get("OCR_PORT", "8000")),
        reload=False,
    )


if __name__ == "__main__":
    main()
