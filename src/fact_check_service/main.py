from __future__ import annotations

from fastapi import FastAPI

from .config import FactCheckConfig
from .knowledge.retrieval import search_facts
from .knowledge.sqlite_store import connect, initialize_schema, status
from .orchestrator import FactCheckOrchestrator
from .schemas import FactSearchRequest, FactSearchResponse, FinalCheckResponse, TextCheckRequest


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
        facts = search_facts(conn, request.query, limit=request.limit)
    return FactSearchResponse(query=request.query, facts=facts)


@app.post("/v1/check/text", response_model=FinalCheckResponse)
def check_text(request: TextCheckRequest) -> FinalCheckResponse:
    orchestrator = FactCheckOrchestrator.from_env()
    return orchestrator.check_text(request)


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
