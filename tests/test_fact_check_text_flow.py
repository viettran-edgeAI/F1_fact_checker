from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fact_check_service.config import FactCheckConfig
from fact_check_service import main as fact_check_main
from fact_check_service.input_adapters import AdapterText
from fact_check_service.main import check_text
from fact_check_service.orchestrator import FactCheckOrchestrator
from fact_check_service.schemas import (
    CheckInputType,
    ClaimVerdict,
    ClassifiedClaim,
    EvidenceItem,
    EvidenceSourceType,
    ExtractedClaim,
    RetrievalRoute,
    TextCheckRequest,
    URLCheckRequest,
    VerdictLabel,
    VerificationStream,
)
from fact_check_service.web_evidence import WebEvidence
from fact_check_service.web_evidence import normalize_search_results, rank_evidence_candidates
from fact_check_service.web_search import BraveSearchClient, BraveSearchConfig


class FakeLLM:
    def __init__(
        self,
        route: VerificationStream | None,
        verdict: str = "true",
        no_claims: bool = False,
        extracted_claims: list[str] | None = None,
        route_by_claim: dict[str, VerificationStream] | None = None,
    ) -> None:
        self.route = route
        self.verdict = verdict
        self.no_claims = no_claims
        self.extracted_claims = extracted_claims
        self.route_by_claim = route_by_claim or {}
        self.search_queries: list[str] = []
        self.extraction_calls = 0

    def extract_claims(self, text: str, *, max_claims: int = 8) -> list[ExtractedClaim]:
        self.extraction_calls += 1
        if self.no_claims:
            return []
        if self.extracted_claims is not None:
            return [
                ExtractedClaim(claim_id=f"C{index}", text=claim_text, source_text=text)
                for index, claim_text in enumerate(self.extracted_claims[:max_claims], start=1)
            ]
        if "Driver X" in text:
            claim_text = "Driver X said Y after the race."
        else:
            claim_text = "Max Verstappen won the 2021 Abu Dhabi Grand Prix."
        return [ExtractedClaim(claim_id="C1", text=claim_text, source_text=text)]

    def classify_claim(self, claim: ExtractedClaim, *, context: str = "") -> ClassifiedClaim:
        route = self.route_by_claim.get(claim.claim_id, self.route or VerificationStream.UNSUPPORTED)
        required_routes = []
        if route == VerificationStream.STRUCTURED:
            required_routes = [RetrievalRoute.STRUCTURED]
        elif route == VerificationStream.WEB:
            required_routes = [RetrievalRoute.WEB]
        elif route == VerificationStream.MIXED:
            required_routes = [RetrievalRoute.STRUCTURED, RetrievalRoute.WEB]
        return ClassifiedClaim(
            **claim.model_dump(),
            verification_stream=route,
            required_routes=required_routes,
            claim_type="statement" if route == VerificationStream.WEB else "race_result",
            unsupported_reason="Not checkable as written." if route == VerificationStream.UNSUPPORTED else None,
        )

    def classify_claims(self, claims: list[ExtractedClaim], *, context: str = "") -> list[ClassifiedClaim]:
        return [self.classify_claim(claim, context=context) for claim in claims]

    def generate_search_query(self, claim: ClassifiedClaim, *, context: str = "") -> str:
        self.search_queries.append(claim.text)
        return f"{claim.text} source"

    def generate_search_queries(self, claims: list[ClassifiedClaim], *, context: str = "") -> dict[str, str]:
        return {claim.claim_id: self.generate_search_query(claim, context=context) for claim in claims}

    def generate_verdict(
        self,
        claim: ClassifiedClaim,
        *,
        structured_evidence: list[dict[str, object]],
        web_evidence: list[dict[str, object]],
    ) -> dict[str, object]:
        return {"verdict": self.verdict, "confidence": "high", "summary": "Evidence supports the claim."}


class FakeUpload:
    filename = "claim.png"
    content_type = "image/png"

    async def read(self) -> bytes:
        return b"\x89PNG\r\n\x1a\n"


def test_schema_serialization_round_trip() -> None:
    claim = ClassifiedClaim(
        claim_id="C1",
        text="Max Verstappen won the 2021 Abu Dhabi Grand Prix.",
        verification_stream=VerificationStream.STRUCTURED,
        claim_type="race_result",
    )
    verdict = ClaimVerdict(
        claim=claim,
        verdict=VerdictLabel.SUPPORTS,
        verification_stream=VerificationStream.STRUCTURED,
        confidence=0.9,
        rationale="Supported by local evidence.",
        evidence=[
            EvidenceItem(
                evidence_id="L1",
                source_type=EvidenceSourceType.LOCAL_DB,
                title="Max Verstappen won the 2021 Abu Dhabi Grand Prix.",
                snippet="Max Verstappen won the 2021 Abu Dhabi Grand Prix for Red Bull.",
            )
        ],
    )

    payload = verdict.model_dump(mode="json")

    assert payload["claim"]["verification_stream"] == "structured"
    assert payload["evidence"][0]["source_type"] == "local_db"


def test_structured_claim_route_uses_local_retrieval() -> None:
    calls: dict[str, int] = {"structured": 0, "web_search": 0}

    def structured_retriever(claim: ClassifiedClaim, limit: int) -> list[dict[str, object]]:
        calls["structured"] += 1
        return [
            {
                "fact_id": 1,
                "fact_text": "Max Verstappen won the 2021 Abu Dhabi Grand Prix for Red Bull.",
                "source": "test",
                "score": 0.1,
            }
        ]

    orchestrator = FactCheckOrchestrator(
        config=FactCheckConfig.from_env(),
        llm_client=FakeLLM(VerificationStream.STRUCTURED),
        structured_retriever=structured_retriever,
        web_searcher=lambda query, count: calls.__setitem__("web_search", calls["web_search"] + 1) or [],
        web_evidence_fetcher=lambda query, results: [],
    )

    response = orchestrator.check_text(TextCheckRequest(text="Max Verstappen won the 2021 Abu Dhabi Grand Prix."))

    assert response.verdict == VerdictLabel.SUPPORTS
    assert calls == {"structured": 1, "web_search": 0}
    assert response.claims[0].meta["verified_by"] == "local_knowledge_database"


def test_web_claim_route_uses_brave_and_web_evidence() -> None:
    calls: dict[str, int] = {"structured": 0, "web_search": 0, "web_fetch": 0}

    def web_search(query: str, count: int) -> list[dict[str, object]]:
        calls["web_search"] += 1
        return [{"title": "Driver X quote", "url": "https://example.com/f1", "snippet": "Driver X said Y."}]

    def web_fetch(query: str, results: list[dict[str, object]]) -> list[WebEvidence]:
        calls["web_fetch"] += 1
        return [
            WebEvidence(
                title="Driver X quote",
                url="https://example.com/f1",
                source="example.com",
                text="Driver X said Y after the race.",
                score=4.2,
            )
        ]

    orchestrator = FactCheckOrchestrator(
        config=FactCheckConfig.from_env(),
        llm_client=FakeLLM(VerificationStream.WEB),
        structured_retriever=lambda claim, limit: calls.__setitem__("structured", calls["structured"] + 1) or [],
        web_searcher=web_search,
        web_evidence_fetcher=web_fetch,
    )

    response = orchestrator.check_text(TextCheckRequest(text="Driver X said Y after the race."))

    assert response.verdict == VerdictLabel.SUPPORTS
    assert calls == {"structured": 0, "web_search": 1, "web_fetch": 1}
    assert response.claims[0].meta["verified_by"] == "brave_search_web_evidence"
    assert response.claims[0].evidence[0].source_type == EvidenceSourceType.WEB
    assert response.claims[0].web_evidence
    assert response.claims[0].web_evidence[0].meta["grounded_by"] == "brave_llm_context"


def test_unsupported_claim_route_skips_retrieval() -> None:
    calls: dict[str, int] = {"structured": 0, "web_search": 0}
    orchestrator = FactCheckOrchestrator(
        config=FactCheckConfig.from_env(),
        llm_client=FakeLLM(VerificationStream.UNSUPPORTED),
        structured_retriever=lambda claim, limit: calls.__setitem__("structured", calls["structured"] + 1) or [],
        web_searcher=lambda query, count: calls.__setitem__("web_search", calls["web_search"] + 1) or [],
        web_evidence_fetcher=lambda query, results: [],
    )

    response = orchestrator.check_text(TextCheckRequest(text="F1 is the best sport."))

    assert response.verdict == VerdictLabel.NOT_ENOUGH_INFO
    assert calls == {"structured": 0, "web_search": 0}
    assert response.unsupported_claims
    assert response.claims[0].meta["verified_by"] == "none"


def test_no_f1_related_claim_returns_early_without_retrieval() -> None:
    calls: dict[str, int] = {"structured": 0, "web_search": 0}
    fake_llm = FakeLLM(VerificationStream.STRUCTURED, no_claims=True)
    orchestrator = FactCheckOrchestrator(
        config=FactCheckConfig.from_env(),
        llm_client=fake_llm,
        structured_retriever=lambda claim, limit: calls.__setitem__("structured", calls["structured"] + 1) or [],
        web_searcher=lambda query, count: calls.__setitem__("web_search", calls["web_search"] + 1) or [],
        web_evidence_fetcher=lambda query, results: [],
    )

    response = orchestrator.check_text(TextCheckRequest(text="The stock market rose today."))

    assert response.verdict == VerdictLabel.NOT_ENOUGH_INFO
    assert response.summary == "No F1-related claim found"
    assert response.meta["reason"] == "no_f1_related_claim_found"
    assert response.claims == []
    assert calls == {"structured": 0, "web_search": 0}
    assert fake_llm.extraction_calls == 0


def test_normalized_url_without_f1_claim_returns_early_with_url_metadata() -> None:
    calls: dict[str, int] = {"structured": 0, "web_search": 0, "web_fetch": 0}
    fake_llm = FakeLLM(VerificationStream.STRUCTURED, no_claims=True)
    orchestrator = FactCheckOrchestrator(
        config=FactCheckConfig.from_env(),
        llm_client=fake_llm,
        structured_retriever=lambda claim, limit: calls.__setitem__("structured", calls["structured"] + 1) or [],
        web_searcher=lambda query, count: calls.__setitem__("web_search", calls["web_search"] + 1) or [],
        web_evidence_fetcher=lambda query, results: calls.__setitem__("web_fetch", calls["web_fetch"] + 1) or [],
    )

    response = orchestrator.check_normalized_text(
        TextCheckRequest(text="The stock market rose today.", input_type=CheckInputType.URL)
    )

    assert response.verdict == VerdictLabel.NOT_ENOUGH_INFO
    assert response.summary == "No F1-related claim found"
    assert response.meta["input_type"] == "url"
    assert response.meta["reason"] == "no_f1_related_claim_found"
    assert response.claims == []
    assert calls == {"structured": 0, "web_search": 0, "web_fetch": 0}
    assert fake_llm.extraction_calls == 0


def test_normalized_image_f1_claim_runs_pipeline_with_image_metadata() -> None:
    calls: dict[str, int] = {"structured": 0, "web_search": 0}

    def structured_retriever(claim: ClassifiedClaim, limit: int) -> list[dict[str, object]]:
        calls["structured"] += 1
        return [
            {
                "fact_id": 1,
                "fact_text": "Max Verstappen won the 2021 Abu Dhabi Grand Prix for Red Bull.",
                "source": "test",
                "score": 0.1,
            }
        ]

    fake_llm = FakeLLM(VerificationStream.STRUCTURED)
    orchestrator = FactCheckOrchestrator(
        config=FactCheckConfig.from_env(),
        llm_client=fake_llm,
        structured_retriever=structured_retriever,
        web_searcher=lambda query, count: calls.__setitem__("web_search", calls["web_search"] + 1) or [],
        web_evidence_fetcher=lambda query, results: [],
    )

    response = orchestrator.check_normalized_text(
        TextCheckRequest(text="Max Verstappen won the 2021 Abu Dhabi Grand Prix.", input_type=CheckInputType.IMAGE)
    )

    assert response.verdict == VerdictLabel.SUPPORTS
    assert response.meta["input_type"] == "image"
    assert response.claims[0].claim.text == "Max Verstappen won the 2021 Abu Dhabi Grand Prix."
    assert response.claims[0].meta["verified_by"] == "local_knowledge_database"
    assert calls == {"structured": 1, "web_search": 0}
    assert fake_llm.extraction_calls == 1


def test_multi_claim_multi_route_pipeline_consolidates_per_claim_evidence() -> None:
    calls = {"structured": 0, "web_search": 0, "web_fetch": 0}

    def structured_retriever(claim: ClassifiedClaim, limit: int) -> list[dict[str, object]]:
        calls["structured"] += 1
        return [
            {
                "fact_id": 1,
                "fact_text": f"Structured evidence for {claim.text}",
                "source": "test",
                "score": 0.1,
            }
        ]

    def web_search(query: str, count: int) -> list[dict[str, object]]:
        calls["web_search"] += 1
        return [{"title": query, "url": f"https://example.com/{count}", "snippet": f"Snippet for {query}"}]

    def web_fetch(query: str, results: list[dict[str, object]]) -> list[WebEvidence]:
        calls["web_fetch"] += 1
        return [
            WebEvidence(
                title=str(results[0]["title"]),
                url=str(results[0]["url"]),
                source="example.com",
                text=f"Fetched evidence for {query}",
                score=4.0,
            )
        ]

    fake_llm = FakeLLM(
        route=None,
        extracted_claims=[
            "Max Verstappen won the 2021 Abu Dhabi Grand Prix.",
            "Driver X said Y after the race.",
            "This claim needs both route types.",
        ],
        route_by_claim={
            "C1": VerificationStream.STRUCTURED,
            "C2": VerificationStream.WEB,
            "C3": VerificationStream.MIXED,
        },
    )
    orchestrator = FactCheckOrchestrator(
        config=FactCheckConfig.from_env(),
        llm_client=fake_llm,
        structured_retriever=structured_retriever,
        web_searcher=web_search,
        web_evidence_fetcher=web_fetch,
    )

    response = orchestrator.check_text(TextCheckRequest(text="multi-claim input"))

    assert len(response.claims) == 3
    assert response.claims[0].structured_evidence
    assert not response.claims[0].web_evidence
    assert response.claims[1].web_evidence
    assert not response.claims[1].structured_evidence
    assert response.claims[2].structured_evidence
    assert response.claims[2].web_evidence
    assert response.claims[2].verification_stream == VerificationStream.MIXED
    assert response.meta["route_counts"]["mixed"] == 1
    assert calls == {"structured": 2, "web_search": 2, "web_fetch": 2}


def test_brave_llm_context_normalizes_grounding_snippets_for_gemma() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "grounding": {
                    "generic": [
                        {
                            "url": "https://www.formula1.com/article/test.123.html",
                            "title": "Formula 1 Article",
                            "snippets": ["First snippet", "Second snippet"],
                        }
                    ]
                },
                "sources": {
                    "https://www.formula1.com/article/test.123.html": {
                        "site_name": "Formula1",
                        "page_last_modified": "2026-06-07T00:00:00Z",
                    }
                },
            },
        )
    )
    config = BraveSearchConfig(
        search_endpoint="https://api.search.brave.com/res/v1/web/search",
        news_endpoint="https://api.search.brave.com/res/v1/news/search",
        llm_context_endpoint="https://api.search.brave.com/res/v1/llm/context",
        count=5,
        timeout_seconds=10.0,
        api_key="test-key",
    )
    client = BraveSearchClient(config)
    with httpx.Client(transport=transport) as http_client:
        results = client.llm_context(
            "latest fia decision",
            client=http_client,
            count=4,
            max_urls=3,
            max_snippets=6,
            max_tokens=1024,
        )

    assert len(results) == 1
    assert results[0]["title"] == "Formula 1 Article"
    assert "First snippet" in str(results[0]["snippet"])
    assert results[0]["source"] == "Formula1"


def test_source_policy_tiers_and_filters_web_evidence() -> None:
    results = normalize_search_results(
        [
            {
                "title": "Official FIA decision",
                "url": "https://www.fia.com/news/f1-decision",
                "snippet": "FIA decision on a Formula 1 penalty.",
            },
            {
                "title": "Forum rumor",
                "url": "https://reddit.com/r/formula1/example",
                "snippet": "A Formula 1 rumor from social media.",
            },
        ],
    )

    ranked = rank_evidence_candidates(
        "FIA Formula 1 penalty decision",
        results,
        {},
        top_n=2,
    )

    assert ranked[0].source == "fia.com"
    assert ranked[0].source_tier == "official"
    assert ranked[1].source_tier == "social_forum"
    assert ranked[0].score > ranked[1].score


def test_include_evidence_false_suppresses_all_evidence_arrays() -> None:
    def structured_retriever(claim: ClassifiedClaim, limit: int) -> list[dict[str, object]]:
        return [
            {
                "fact_id": 1,
                "fact_text": "Max Verstappen won the 2021 Abu Dhabi Grand Prix for Red Bull.",
                "source": "test",
                "score": 0.1,
            }
        ]

    orchestrator = FactCheckOrchestrator(
        config=FactCheckConfig.from_env(),
        llm_client=FakeLLM(VerificationStream.STRUCTURED),
        structured_retriever=structured_retriever,
        web_searcher=lambda query, count: [],
        web_evidence_fetcher=lambda query, results: [],
    )

    response = orchestrator.check_text(
        TextCheckRequest(
            text="Max Verstappen won the 2021 Abu Dhabi Grand Prix.",
            include_evidence=False,
        )
    )

    assert response.claims[0].verdict == VerdictLabel.SUPPORTS
    assert response.claims[0].evidence == []
    assert response.claims[0].structured_evidence == []
    assert response.claims[0].web_evidence == []


def test_check_text_forces_text_input_type_metadata() -> None:
    orchestrator = FactCheckOrchestrator(
        config=FactCheckConfig.from_env(),
        llm_client=FakeLLM(VerificationStream.STRUCTURED, no_claims=True),
        structured_retriever=lambda claim, limit: [],
        web_searcher=lambda query, count: [],
        web_evidence_fetcher=lambda query, results: [],
    )

    response = orchestrator.check_text(
        TextCheckRequest(text="The stock market rose today.", input_type=CheckInputType.URL)
    )

    assert response.verdict == VerdictLabel.NOT_ENOUGH_INFO
    assert response.meta["input_type"] == "text"
    assert response.meta["reason"] == "no_f1_related_claim_found"


def test_url_endpoint_normalizes_text_and_uses_url_gate_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_from_env() -> FactCheckOrchestrator:
        return FactCheckOrchestrator(
            config=FactCheckConfig.from_env(),
            llm_client=FakeLLM(VerificationStream.STRUCTURED, no_claims=True),
            structured_retriever=lambda claim, limit: [],
            web_searcher=lambda query, count: [],
            web_evidence_fetcher=lambda query, results: [],
        )

    def fake_fetch_url_text(url: str, *, config: FactCheckConfig) -> AdapterText:
        return AdapterText(
            text="The stock market rose today.",
            meta={"source_url": url, "content_type": "text/html", "bytes_read": 128, "truncated": False},
        )

    monkeypatch.setattr(fact_check_main.FactCheckOrchestrator, "from_env", staticmethod(fake_from_env))
    monkeypatch.setattr(fact_check_main, "fetch_url_text", fake_fetch_url_text)

    response = fact_check_main.check_url(
        URLCheckRequest(url="https://example.com/not-f1", meta={"session_id": "session-url"})
    )

    assert response.text == "The stock market rose today."
    assert response.meta["input_type"] == "url"
    assert response.meta["reason"] == "no_f1_related_claim_found"
    assert response.meta["session_id"] == "session-url"
    assert response.meta["source_url"] == "https://example.com/not-f1"
    assert response.meta["url_metadata"]["bytes_read"] == 128


def test_image_endpoint_ocr_text_runs_normalized_image_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, int] = {"structured": 0}

    def fake_from_env() -> FactCheckOrchestrator:
        return FactCheckOrchestrator(
            config=FactCheckConfig.from_env(),
            llm_client=FakeLLM(VerificationStream.STRUCTURED),
            structured_retriever=lambda claim, limit: calls.__setitem__("structured", calls["structured"] + 1)
            or [
                {
                    "fact_id": 1,
                    "fact_text": "Max Verstappen won the 2021 Abu Dhabi Grand Prix for Red Bull.",
                    "source": "test",
                }
            ],
            web_searcher=lambda query, count: [],
            web_evidence_fetcher=lambda query, results: [],
        )

    def fake_ocr_image_text(
        *,
        filename: str,
        content_type: str,
        body: bytes,
        config: FactCheckConfig,
    ) -> AdapterText:
        assert filename == "claim.png"
        assert content_type == "image/png"
        assert body.startswith(b"\x89PNG")
        return AdapterText(
            text="Max Verstappen won the 2021 Abu Dhabi Grand Prix.",
            meta={"job_id": "ocr-test", "line_count": 1, "ocr_meta": {}},
        )

    monkeypatch.setattr(fact_check_main.FactCheckOrchestrator, "from_env", staticmethod(fake_from_env))
    monkeypatch.setattr(fact_check_main, "ocr_image_text", fake_ocr_image_text)

    response = asyncio.run(fact_check_main.check_image(FakeUpload(), meta='{"session_id": "session-image"}'))

    assert response.verdict == VerdictLabel.SUPPORTS
    assert response.meta["input_type"] == "image"
    assert response.meta["session_id"] == "session-image"
    assert response.meta["ocr_metadata"]["job_id"] == "ocr-test"
    assert calls == {"structured": 1}


def test_f1_related_without_checkable_claims_returns_early() -> None:
    calls: dict[str, int] = {"structured": 0, "web_search": 0}
    orchestrator = FactCheckOrchestrator(
        config=FactCheckConfig.from_env(),
        llm_client=FakeLLM(VerificationStream.STRUCTURED, no_claims=True),
        structured_retriever=lambda claim, limit: calls.__setitem__("structured", calls["structured"] + 1) or [],
        web_searcher=lambda query, count: calls.__setitem__("web_search", calls["web_search"] + 1) or [],
        web_evidence_fetcher=lambda query, results: [],
    )

    response = orchestrator.check_text(TextCheckRequest(text="Formula 1 is exciting to watch."))

    assert response.verdict == VerdictLabel.NOT_ENOUGH_INFO
    assert response.summary == "No F1-related claim found"
    assert response.meta["reason"] == "no_f1_related_claim_found"
    assert response.claims == []
    assert calls == {"structured": 0, "web_search": 0}


def test_text_endpoint_validation_and_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_from_env() -> FactCheckOrchestrator:
        return FactCheckOrchestrator(
            config=FactCheckConfig.from_env(),
            llm_client=FakeLLM(VerificationStream.STRUCTURED),
            structured_retriever=lambda claim, limit: [
                {
                    "fact_id": 1,
                    "fact_text": "Max Verstappen won the 2021 Abu Dhabi Grand Prix for Red Bull.",
                    "source": "test",
                }
            ],
            web_searcher=lambda query, count: [],
            web_evidence_fetcher=lambda query, results: [],
        )

    monkeypatch.setattr(FactCheckOrchestrator, "from_env", staticmethod(fake_from_env))

    with pytest.raises(ValidationError):
        TextCheckRequest(text="")

    response = check_text(TextCheckRequest(text="Max Verstappen won the 2021 Abu Dhabi Grand Prix."))
    payload = response.model_dump(mode="json")

    assert payload["claims"][0]["verification_stream"] == "structured"
    assert payload["claims"][0]["meta"]["verified_by"] == "local_knowledge_database"
