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
from fact_check_service.llm_client import LLMClient, _compact_evidence
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
from fact_check_service.web_evidence import fetch_article_texts, normalize_search_results, rank_evidence_candidates
from fact_check_service.web_search import BraveSearchClient, BraveSearchConfig


class FakeLLM:
    def __init__(
        self,
        route: VerificationStream | None,
        verdict: str = "true",
        no_claims: bool = False,
        extracted_claims: list[str] | None = None,
        route_by_claim: dict[str, VerificationStream] | None = None,
        rewritten_claims: dict[str, str] | None = None,
    ) -> None:
        self.route = route
        self.verdict = verdict
        self.no_claims = no_claims
        self.extracted_claims = extracted_claims
        self.route_by_claim = route_by_claim or {}
        self.rewritten_claims = rewritten_claims or {}
        self.search_queries: list[str] = []
        self.verdict_thinking_flags: list[bool] = []
        self.extraction_calls = 0
        self.rewrite_calls: list[list[str]] = []

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

    def complete_claim_contexts(
        self,
        claims: list[ClassifiedClaim],
        *,
        context: str = "",
    ) -> dict[str, str]:
        self.rewrite_calls.append([claim.claim_id for claim in claims])
        return {
            claim.claim_id: self.rewritten_claims.get(claim.claim_id, claim.text)
            for claim in claims
        }

    def rewrite_structured_claims(
        self,
        claims: list[ClassifiedClaim],
        *,
        context: str = "",
    ) -> dict[str, str]:
        return self.complete_claim_contexts(claims, context=context)

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
        enable_thinking: bool = False,
    ) -> dict[str, object]:
        self.verdict_thinking_flags.append(enable_thinking)
        return {"verdict": self.verdict, "confidence": "high", "summary": "Evidence supports the claim."}

    def generate_verdict_stream(
        self,
        claim: ClassifiedClaim,
        *,
        structured_evidence: list[dict[str, object]],
        web_evidence: list[dict[str, object]],
        on_token=None,
    ) -> dict[str, object]:
        if on_token is not None:
            on_token('{"verdict":"', "answer")
            on_token(f'{self.verdict}"', "answer")
        return self.generate_verdict(
            claim,
            structured_evidence=structured_evidence,
            web_evidence=web_evidence,
            enable_thinking=False,
        )


class CaptureHTTPClient:
    def __init__(self) -> None:
        self.payloads: list[dict[str, object]] = []

    def post(self, url: str, *, json: dict[str, object]) -> httpx.Response:
        self.payloads.append(json)
        return httpx.Response(
            200,
            json={"answer": "{\"verdict\":\"true\",\"confidence\":\"high\",\"summary\":\"ok\"}"},
            request=httpx.Request("POST", url),
        )


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


def test_llm_client_verdict_payload_uses_compact_fast_mode() -> None:
    capture_client = CaptureHTTPClient()
    llm = LLMClient(config=FactCheckConfig.from_env(), client=capture_client)  # type: ignore[arg-type]
    claim = ClassifiedClaim(
        claim_id="C1",
        text="Driver X said Y after the race.",
        verification_stream=VerificationStream.WEB,
        required_routes=[RetrievalRoute.WEB],
    )

    llm.generate_verdict(claim, structured_evidence=[], web_evidence=[{"snippet": "Driver X said Y."}])

    payload = capture_client.payloads[-1]
    assert payload["enable_thinking"] is False
    assert payload["thinking_mode"] == "fast"
    assert payload["max_tokens"] == 384


def test_llm_client_verdict_ignores_thinking_for_compact_json() -> None:
    capture_client = CaptureHTTPClient()
    llm = LLMClient(config=FactCheckConfig.from_env(), client=capture_client)  # type: ignore[arg-type]
    claim = ClassifiedClaim(
        claim_id="C1",
        text="This mixed F1 claim needs broader evidence.",
        verification_stream=VerificationStream.MIXED,
        required_routes=[RetrievalRoute.STRUCTURED, RetrievalRoute.WEB],
    )

    llm.generate_verdict(
        claim,
        structured_evidence=[{"snippet": "Structured evidence."}],
        web_evidence=[{"snippet": "Web evidence."}],
    )

    payload = capture_client.payloads[-1]
    assert payload["enable_thinking"] is False
    assert payload["thinking_mode"] == "fast"
    assert payload["max_tokens"] == 384


def test_llm_client_streaming_verdict_forwards_tokens_and_parses_done() -> None:
    events = [
        'event: token\ndata: {"delta":"{\\"verdict\\":\\"","kind":"answer"}\n\n',
        'event: token\ndata: {"delta":"true\\"}","kind":"answer"}\n\n',
        'event: done\ndata: {"answer":"{\\"verdict\\":\\"true\\",\\"confidence\\":\\"high\\",\\"summary\\":\\"ok\\"}","elapsed_ms":100,"completion_tokens":2,"tokens_per_second":20.0}\n\n',
    ]
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            content="".join(events).encode("utf-8"),
            request=request,
        )
    )
    tokens: list[str] = []
    llm = LLMClient(config=FactCheckConfig.from_env(), client=httpx.Client(transport=transport))
    claim = ClassifiedClaim(
        claim_id="C1",
        text="Driver X said Y after the race.",
        verification_stream=VerificationStream.WEB,
        required_routes=[RetrievalRoute.WEB],
    )

    payload = llm.generate_verdict_stream(
        claim,
        structured_evidence=[],
        web_evidence=[{"snippet": "Driver X said Y."}],
        on_token=lambda delta, kind: tokens.append(delta),
    )

    assert payload["verdict"] == "true"
    assert "".join(tokens) == '{"verdict":"true"}'
    assert llm.call_metrics[-1]["tokens_per_second"] == 20.0


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


def test_claim_context_completion_runs_after_planning_and_before_structured_retrieval() -> None:
    seen_queries: list[str] = []

    def structured_retriever(claim: ClassifiedClaim, limit: int) -> list[dict[str, object]]:
        seen_queries.append(claim.structured_query or claim.text)
        return [
            {
                "fact_id": 1,
                "fact_text": "Red Bull won the 2023 Formula 1 Constructors' Championship.",
                "source": "test",
                "score": 0.1,
            }
        ]

    fake_llm = FakeLLM(
        VerificationStream.STRUCTURED,
        extracted_claims=["Red Bull won the Constructors' Championship."],
        rewritten_claims={"C1": "Red Bull won the 2023 Formula 1 Constructors' Championship."},
    )
    orchestrator = FactCheckOrchestrator(
        config=FactCheckConfig.from_env(),
        llm_client=fake_llm,
        structured_retriever=structured_retriever,
        web_searcher=lambda query, count: [],
        web_evidence_fetcher=lambda query, results: [],
    )

    response = orchestrator.check_text(
        TextCheckRequest(
            text=(
                "Max Verstappen dominated the 2023 Formula 1 season. "
                "He won the World Drivers' Championship and Red Bull won the Constructors' Championship."
            )
        )
    )

    assert fake_llm.rewrite_calls == [["C1"]]
    assert "2023 Formula 1 Constructors' Championship" in response.claims[0].claim.text
    assert "2023 Formula 1 Constructors' Championship" in seen_queries[0]
    assert response.meta["timings_ms"]["claim_context_completion"] >= 0


def test_claim_context_completion_updates_web_claim_before_query_generation() -> None:
    seen_queries: list[str] = []

    def web_search(query: str, count: int) -> list[dict[str, object]]:
        seen_queries.append(query)
        return [
            {
                "title": "Ferrari lineup report",
                "url": "https://example.com/ferrari-lineup",
                "snippet": "Ferrari has not confirmed a driver lineup change.",
            }
        ]

    def web_fetch(query: str, results: list[dict[str, object]]) -> list[WebEvidence]:
        return [
            WebEvidence(
                title="Ferrari lineup report",
                url="https://example.com/ferrari-lineup",
                source="example.com",
                text="Ferrari has not confirmed a driver lineup change.",
                score=4.2,
            )
        ]

    fake_llm = FakeLLM(
        VerificationStream.WEB,
        extracted_claims=["No official team statement has confirmed the story."],
        rewritten_claims={
            "C1": "No official Ferrari team statement has confirmed the reported future driver lineup disagreement."
        },
    )
    orchestrator = FactCheckOrchestrator(
        config=FactCheckConfig.from_env(),
        llm_client=fake_llm,
        structured_retriever=lambda claim, limit: [],
        web_searcher=web_search,
        web_evidence_fetcher=web_fetch,
    )

    response = orchestrator.check_text(
        TextCheckRequest(
            text=(
                "Ferrari is facing internal disagreement over its future driver lineup. "
                "No official team statement has confirmed the story."
            )
        )
    )

    assert fake_llm.rewrite_calls == [["C1"]]
    assert response.claims[0].claim.text == (
        "No official Ferrari team statement has confirmed the reported future driver lineup disagreement."
    )
    assert fake_llm.search_queries == [
        "No official Ferrari team statement has confirmed the reported future driver lineup disagreement."
    ]
    assert seen_queries == [
        "No official Ferrari team statement has confirmed the reported future driver lineup disagreement. source"
    ]
    assert response.claims[0].claim.meta["claim_context_completed"] is True
    assert response.claims[0].claim.meta["structured_claim_rewritten"] is False


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

    fake_llm = FakeLLM(VerificationStream.WEB)
    orchestrator = FactCheckOrchestrator(
        config=FactCheckConfig.from_env(),
        llm_client=fake_llm,
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
    assert fake_llm.verdict_thinking_flags == [False]


def test_streaming_pipeline_emits_stage_events_and_gemma_tokens() -> None:
    events: list[dict[str, object]] = []

    def web_search(query: str, count: int) -> list[dict[str, object]]:
        return [{"title": "Driver X quote", "url": "https://example.com/f1", "snippet": "Driver X said Y."}]

    def web_fetch(query: str, results: list[dict[str, object]]) -> list[WebEvidence]:
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
        structured_retriever=lambda claim, limit: [],
        web_searcher=web_search,
        web_evidence_fetcher=web_fetch,
    )

    response = orchestrator.check_text(
        TextCheckRequest(text="Driver X said Y after the race."),
        event_callback=events.append,
    )

    event_names = [str(event["event"]) for event in events]
    assert response.verdict == VerdictLabel.SUPPORTS
    assert "claim_extraction_started" in event_names
    assert "web_retrieval_started" in event_names
    assert "verdict_generation_started" in event_names
    assert "result_aggregation_finished" in event_names
    assert any(event["event"] == "gemma_token" and event.get("delta") for event in events)


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
    assert response.summary == "No information related to F1 could be extracted."
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
    assert response.summary == "No information related to F1 could be extracted."
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
    assert fake_llm.verdict_thinking_flags == [False, False]


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


def test_web_evidence_fetches_article_text_even_with_long_context_snippet() -> None:
    results = normalize_search_results(
        [
            {
                "title": "F1 team driver lineup report",
                "url": "https://example.com/f1-lineup",
                "snippet": " ".join(["Long Brave context snippet"] * 40),
            }
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://example.com/f1-lineup"
        html = """
        <html><head><title>F1 team driver lineup report</title></head>
        <body>
          <article>
            <p>Article body says the team principal denied there was any split over the lineup.</p>
            <p>The report also says no official signing announcement has been made.</p>
          </article>
        </body></html>
        """
        return httpx.Response(200, headers={"content-type": "text/html"}, text=html)

    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        article_texts = fetch_article_texts(results, client=client)

    assert "team principal denied" in article_texts["https://example.com/f1-lineup"]
    assert "official signing announcement" in article_texts["https://example.com/f1-lineup"]


def test_compact_evidence_keeps_article_body_context_for_verdict_prompt() -> None:
    article_body = (
        "Lead sentence. "
        + ("Background sentence. " * 30)
        + "Deep article context says the reported split was denied by the team principal."
    )
    compacted = _compact_evidence(
        [
            {
                "evidence_id": "W1",
                "source_type": "web",
                "title": "F1 team driver lineup report",
                "snippet": "",
                "url": "https://example.com/f1-lineup",
                "source_id": "example.com",
                "score": 0.8,
                "meta": {"text": article_body},
            }
        ]
    )

    assert compacted[0]["title"] == "F1 team driver lineup report"
    assert "Deep article context" in compacted[0]["snippet"]
    assert len(str(compacted[0]["snippet"])) <= 1200


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
    assert response.summary == "No information related to F1 could be extracted."
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
