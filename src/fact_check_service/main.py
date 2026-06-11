from __future__ import annotations

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

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


@app.post("/v1/check/url", response_model=FinalCheckResponse)
def check_url(request: URLCheckRequest) -> FinalCheckResponse:
    orchestrator = FactCheckOrchestrator.from_env()
    try:
        adapter_text = fetch_url_text(request.url, config=orchestrator.config)
    except InputAdapterError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return orchestrator.check_normalized_text(text_request_from_url(request, adapter_text))


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
