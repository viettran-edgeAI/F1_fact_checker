from __future__ import annotations

import json
import queue
import threading
from collections.abc import Callable, Iterator
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from .config import FactCheckConfig
from .input_adapters import (
    InputAdapterError,
    fetch_url_text,
    ocr_image_text,
    parse_multipart_meta,
    text_request_from_image,
    text_request_from_url,
)
from .knowledge.retrieval import search_facts
from .knowledge.sqlite_store import connect, initialize_schema, status
from .orchestrator import FactCheckOrchestrator
from .schemas import FactSearchRequest, FactSearchResponse, FinalCheckResponse, TextCheckRequest, URLCheckRequest


app = FastAPI(title="F1 Fact Check Service", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/knowledge/status")
def knowledge_status() -> dict[str, object]:
    config = FactCheckConfig.from_env()
    with connect(config.db_path) as conn:
        initialize_schema(conn)
        payload = status(conn)
    payload["db_path"] = str(config.db_path)
    return payload


@app.post("/v1/knowledge/search", response_model=FactSearchResponse)
def knowledge_search(request: FactSearchRequest) -> FactSearchResponse:
    config = FactCheckConfig.from_env()
    with connect(config.db_path) as conn:
        initialize_schema(conn)
        facts = search_facts(conn, request.query, limit=request.limit, config=config)
    return FactSearchResponse(query=request.query, facts=facts)


@app.post("/v1/check/text", response_model=FinalCheckResponse)
def check_text(request: TextCheckRequest) -> FinalCheckResponse:
    orchestrator = FactCheckOrchestrator.from_env()
    return orchestrator.check_text(request)


@app.post("/v1/check/text/stream")
def check_text_stream(request: TextCheckRequest) -> StreamingResponse:
    def run(emit: Callable[[dict[str, Any]], None]) -> FinalCheckResponse:
        orchestrator = FactCheckOrchestrator.from_env()
        return orchestrator.check_text(request, event_callback=emit)

    return _stream_response(run)


@app.post("/v1/check/url", response_model=FinalCheckResponse)
def check_url(request: URLCheckRequest) -> FinalCheckResponse:
    orchestrator = FactCheckOrchestrator.from_env()
    try:
        adapter_text = fetch_url_text(request.url, config=orchestrator.config)
    except InputAdapterError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return orchestrator.check_normalized_text(text_request_from_url(request, adapter_text))


@app.post("/v1/check/url/stream")
def check_url_stream(request: URLCheckRequest) -> StreamingResponse:
    def run(emit: Callable[[dict[str, Any]], None]) -> FinalCheckResponse:
        orchestrator = FactCheckOrchestrator.from_env()
        try:
            emit({"event": "url_fetch_started", "stage": "url_fetch", "status": "started"})
            adapter_text = fetch_url_text(request.url, config=orchestrator.config)
            emit({"event": "url_fetch_finished", "stage": "url_fetch", "status": "finished"})
        except InputAdapterError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        return orchestrator.check_normalized_text(
            text_request_from_url(request, adapter_text),
            event_callback=emit,
        )

    return _stream_response(run)


@app.post("/v1/check/image", response_model=FinalCheckResponse)
async def check_image(
    image: UploadFile = File(...),
    meta: str | None = Form(default=None),
) -> FinalCheckResponse:
    orchestrator = FactCheckOrchestrator.from_env()
    try:
        request_meta = parse_multipart_meta(meta)
        body = await image.read()
        adapter_text = ocr_image_text(
            filename=image.filename or "upload.png",
            content_type=image.content_type or "application/octet-stream",
            body=body,
            config=orchestrator.config,
        )
    except InputAdapterError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    options = TextCheckRequest(text=adapter_text.text, meta=request_meta)
    return orchestrator.check_normalized_text(
        text_request_from_image(text=adapter_text.text, meta=adapter_text.meta, options=options)
    )


@app.post("/v1/check/image/stream")
async def check_image_stream(
    image: UploadFile = File(...),
    meta: str | None = Form(default=None),
) -> StreamingResponse:
    try:
        request_meta = parse_multipart_meta(meta)
    except InputAdapterError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    body = await image.read()
    filename = image.filename or "upload.png"
    content_type = image.content_type or "application/octet-stream"

    def run(emit: Callable[[dict[str, Any]], None]) -> FinalCheckResponse:
        orchestrator = FactCheckOrchestrator.from_env()
        try:
            emit({"event": "ocr_started", "stage": "ocr", "status": "started"})
            adapter_text = ocr_image_text(
                filename=filename,
                content_type=content_type,
                body=body,
                config=orchestrator.config,
            )
            emit({"event": "ocr_finished", "stage": "ocr", "status": "finished"})
        except InputAdapterError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

        options = TextCheckRequest(text=adapter_text.text, meta=request_meta)
        return orchestrator.check_normalized_text(
            text_request_from_image(text=adapter_text.text, meta=adapter_text.meta, options=options),
            event_callback=emit,
        )

    return _stream_response(run)


def _stream_response(
    run: Callable[[Callable[[dict[str, Any]], None]], FinalCheckResponse],
) -> StreamingResponse:
    return StreamingResponse(
        _stream_events(run),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _stream_events(
    run: Callable[[Callable[[dict[str, Any]], None]], FinalCheckResponse],
) -> Iterator[str]:
    event_queue: queue.Queue[dict[str, Any] | None] = queue.Queue()

    def emit(event: dict[str, Any]) -> None:
        event_queue.put(event)

    def worker() -> None:
        try:
            result = run(emit)
            event_queue.put({"event": "done", "result": result.model_dump(mode="json")})
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else "Fact-check stream failed."
            event_queue.put({"event": "error", "detail": detail, "status_code": exc.status_code})
        except Exception as exc:  # pragma: no cover - defensive stream boundary
            event_queue.put({"event": "error", "detail": f"Fact-check stream failed: {exc}"})
        finally:
            event_queue.put(None)

    threading.Thread(target=worker, daemon=True).start()
    while True:
        item = event_queue.get()
        if item is None:
            break
        event_name = str(item.get("event") or "message")
        payload = {key: value for key, value in item.items() if key != "event"}
        yield _sse_event(event_name, payload)


def _sse_event(event: str, payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {body}\n\n"


def main() -> None:
    import os

    import uvicorn

    uvicorn.run(
        "fact_check_service.main:app",
        host=os.environ.get("FACT_CHECK_HOST", "0.0.0.0"),
        port=int(os.environ.get("FACT_CHECK_PORT", "8082")),
        reload=False,
    )


if __name__ == "__main__":
    main()
