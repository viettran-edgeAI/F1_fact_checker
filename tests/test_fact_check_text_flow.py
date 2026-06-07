from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fact_check_service.config import FactCheckConfig
from fact_check_service.main import check_text
from fact_check_service.orchestrator import FactCheckOrchestrator
from fact_check_service.schemas import (
    ClaimVerdict,
    ClassifiedClaim,
    EvidenceItem,
    EvidenceSourceType,
    ExtractedClaim,
    F1RelevanceLabel,
    F1RelevanceResult,
    TextCheckRequest,
    VerdictLabel,
    VerificationStream,
)
from fact_check_service.web_evidence import WebEvidence


class FakeLLM:
    def __init__(
        self,
        route: VerificationStream,
        verdict: str = "true",
        relevance: F1RelevanceLabel = F1RelevanceLabel.F1_RELATED,
        no_claims: bool = False,
    ) -> None:
        self.route = route
        self.verdict = verdict
        self.relevance = relevance
        self.no_claims = no_claims
        self.search_queries: list[str] = []
        self.extraction_calls = 0

    def classify_f1_relevance(self, text: str) -> F1RelevanceResult:
        return F1RelevanceResult(label=self.relevance, confidence=0.9, reason="test")

    def extract_claims(self, text: str, *, max_claims: int = 8) -> list[ExtractedClaim]:
        self.extraction_calls += 1
        if self.no_claims:
            return []
        if "Driver X" in text:
            claim_text = "Driver X said Y after the race."
        else:
            claim_text = "Max Verstappen won the 2021 Abu Dhabi Grand Prix."
        return [ExtractedClaim(claim_id="C1", text=claim_text, source_text=text)]

    def classify_claim(self, claim: ExtractedClaim, *, context: str = "") -> ClassifiedClaim:
        return ClassifiedClaim(
            **claim.model_dump(),
            verification_stream=self.route,
            claim_type="statement" if self.route == VerificationStream.WEB else "race_result",
            unsupported_reason="Not checkable as written." if self.route == VerificationStream.UNSUPPORTED else None,
        )

    def generate_search_query(self, claim: ClassifiedClaim, *, context: str = "") -> str:
        self.search_queries.append(claim.text)
        return f"{claim.text} source"

    def generate_verdict(
        self,
        claim: ClassifiedClaim,
        *,
        structured_evidence: list[dict[str, object]],
        web_evidence: list[dict[str, object]],
    ) -> dict[str, object]:
        return {"verdict": self.verdict, "confidence": "high", "summary": "Evidence supports the claim."}


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


def test_not_f1_related_returns_early_without_extraction_or_retrieval() -> None:
    calls: dict[str, int] = {"structured": 0, "web_search": 0}
    fake_llm = FakeLLM(VerificationStream.STRUCTURED, relevance=F1RelevanceLabel.NOT_F1_RELATED)
    orchestrator = FactCheckOrchestrator(
        config=FactCheckConfig.from_env(),
        llm_client=fake_llm,
        structured_retriever=lambda claim, limit: calls.__setitem__("structured", calls["structured"] + 1) or [],
        web_searcher=lambda query, count: calls.__setitem__("web_search", calls["web_search"] + 1) or [],
        web_evidence_fetcher=lambda query, results: [],
    )

    response = orchestrator.check_text(TextCheckRequest(text="The stock market rose today."))

    assert response.verdict == VerdictLabel.NOT_ENOUGH_INFO
    assert response.summary == "This content is not related to Formula 1. No fact-check was performed."
    assert response.meta["reason"] == "not_f1_related"
    assert response.claims == []
    assert calls == {"structured": 0, "web_search": 0}
    assert fake_llm.extraction_calls == 0


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
    assert response.summary == "F1-related content found, but no checkable claim detected."
    assert response.meta["reason"] == "no_checkable_claims"
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
