from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from .config import FactCheckConfig
from .llm_client import LLMClient
from .retrieval import retrieve_structured_evidence
from .schemas import (
    ClaimVerdict,
    ClassifiedClaim,
    EvidenceItem,
    EvidenceSourceType,
    FinalCheckResponse,
    TextCheckRequest,
    VerdictLabel,
    VerificationStream,
)
from .web_evidence import WebEvidence, fetch_ranked_evidence_from_results
from .web_search import BraveSearchClient, BraveSearchError


StructuredRetriever = Callable[[ClassifiedClaim, int], list[dict[str, Any]]]
WebSearcher = Callable[[str, int], list[dict[str, Any]]]
WebEvidenceFetcher = Callable[[str, list[dict[str, Any]]], list[WebEvidence]]


@dataclass(slots=True)
class FactCheckOrchestrator:
    config: FactCheckConfig
    llm_client: LLMClient
    structured_retriever: StructuredRetriever | None = None
    web_searcher: WebSearcher | None = None
    web_evidence_fetcher: WebEvidenceFetcher | None = None

    @classmethod
    def from_env(cls) -> "FactCheckOrchestrator":
        config = FactCheckConfig.from_env()
        return cls(config=config, llm_client=LLMClient(config=config))

    def check_text(self, request: TextCheckRequest) -> FinalCheckResponse:
        started = time.perf_counter()
        timings: dict[str, int] = {}
        warnings: list[str] = []

        extract_started = time.perf_counter()
        extracted_claims = self.llm_client.extract_claims(request.text, max_claims=request.max_claims)
        timings["claim_extraction"] = _elapsed_ms(extract_started)

        classified_claims: list[ClassifiedClaim] = []
        verdicts: list[ClaimVerdict] = []

        classify_started = time.perf_counter()
        for claim in extracted_claims:
            classified = self.llm_client.classify_claim(claim, context=request.text)
            if classified.verification_stream not in request.verification_streams:
                classified = classified.model_copy(
                    update={
                        "verification_stream": VerificationStream.UNSUPPORTED,
                        "unsupported_reason": "Verification stream disabled for this request.",
                    }
                )
            classified_claims.append(classified)
        timings["claim_classification"] = _elapsed_ms(classify_started)

        for claim in classified_claims:
            route_started = time.perf_counter()
            verdict, route_warnings = self._check_claim(claim, request)
            verdicts.append(verdict)
            warnings.extend(route_warnings)
            timings[f"claim_{claim.claim_id}"] = _elapsed_ms(route_started)

        timings["total"] = _elapsed_ms(started)
        unsupported_claims = [
            claim for claim in classified_claims if claim.verification_stream == VerificationStream.UNSUPPORTED
        ]
        return FinalCheckResponse(
            text=request.text,
            verdict=_aggregate_verdict(verdicts),
            claims=verdicts,
            summary=_summary(verdicts, unsupported_claims),
            unsupported_claims=unsupported_claims,
            meta={
                "run_id": f"run_{uuid.uuid4().hex}",
                "input_type": "text",
                "warnings": warnings,
                "timings_ms": timings,
            },
        )

    def _check_claim(self, claim: ClassifiedClaim, request: TextCheckRequest) -> tuple[ClaimVerdict, list[str]]:
        warnings: list[str] = []
        if claim.verification_stream == VerificationStream.UNSUPPORTED:
            return (
                ClaimVerdict(
                    claim=claim,
                    verdict=VerdictLabel.NOT_ENOUGH_INFO,
                    verification_stream=VerificationStream.UNSUPPORTED,
                    confidence=0.0,
                    rationale=claim.unsupported_reason or "The claim is unsupported or not checkable as written.",
                    evidence=[],
                    meta={"verified_by": "none"},
                ),
                warnings,
            )

        structured_evidence: list[EvidenceItem] = []
        web_evidence: list[EvidenceItem] = []

        if claim.verification_stream in (VerificationStream.STRUCTURED, VerificationStream.MIXED):
            structured_evidence = self._structured_evidence(claim, limit=request.top_k)

        if claim.verification_stream in (VerificationStream.WEB, VerificationStream.MIXED):
            try:
                web_evidence = self._web_evidence(claim)
            except (BraveSearchError, httpx.HTTPError) as exc:
                warnings.append(f"Web evidence retrieval failed for {claim.claim_id}: {exc}")
                web_evidence = []

        evidence = structured_evidence + web_evidence
        if not evidence:
            return (
                ClaimVerdict(
                    claim=claim,
                    verdict=VerdictLabel.NOT_ENOUGH_INFO,
                    verification_stream=claim.verification_stream,
                    confidence=0.0,
                    rationale="No relevant evidence was found for this claim.",
                    evidence=[],
                    meta={"verified_by": _verified_by(claim.verification_stream)},
                ),
                warnings,
            )

        raw_verdict = self.llm_client.generate_verdict(
            claim,
            structured_evidence=[item.model_dump(mode="json") for item in structured_evidence],
            web_evidence=[item.model_dump(mode="json") for item in web_evidence],
        )
        return (_claim_verdict_from_llm(claim, evidence, raw_verdict), warnings)

    def _structured_evidence(self, claim: ClassifiedClaim, *, limit: int) -> list[EvidenceItem]:
        retriever = self.structured_retriever or _default_structured_retriever
        rows = retriever(claim, limit)
        return [_local_evidence_item(index, row) for index, row in enumerate(rows, start=1)]

    def _web_evidence(self, claim: ClassifiedClaim) -> list[EvidenceItem]:
        query = self.llm_client.generate_search_query(claim)
        searcher = self.web_searcher or _default_web_searcher(self.config)
        fetcher = self.web_evidence_fetcher or _default_web_evidence_fetcher(self.config)
        results = searcher(query, self.config.brave_search_count)
        article_evidence = fetcher(query, results)
        return [_web_evidence_item(index, item) for index, item in enumerate(article_evidence, start=1)]


def _default_structured_retriever(claim: ClassifiedClaim, limit: int) -> list[dict[str, Any]]:
    return retrieve_structured_evidence(
        {
            "claim": claim.structured_query or claim.text,
            "entities": {str(index): value for index, value in enumerate(claim.entities)},
            "verification_stream": "structured",
        },
        limit=limit,
    )


def _default_web_searcher(config: FactCheckConfig) -> WebSearcher:
    client = BraveSearchClient()

    def search(query: str, count: int) -> list[dict[str, Any]]:
        return client.search(query, count=count)

    return search


def _default_web_evidence_fetcher(config: FactCheckConfig) -> WebEvidenceFetcher:
    def fetch(query: str, results: list[dict[str, Any]]) -> list[WebEvidence]:
        return fetch_ranked_evidence_from_results(
            query,
            results,
            top_n=min(3, config.brave_search_count),
            timeout_seconds=config.brave_search_timeout,
        )

    return fetch


def _local_evidence_item(index: int, row: dict[str, Any]) -> EvidenceItem:
    fact_id = row.get("fact_id")
    return EvidenceItem(
        evidence_id=f"L{index}",
        source_type=EvidenceSourceType.LOCAL_DB,
        title=str(row.get("title") or row.get("fact_text") or ""),
        snippet=str(row.get("fact_text") or row.get("text") or ""),
        source_id=str(row.get("source") or "local_knowledge_database"),
        table="facts",
        record_id=str(fact_id) if fact_id is not None else None,
        score=_float_or_none(row.get("score")),
        meta=dict(row),
    )


def _web_evidence_item(index: int, item: WebEvidence) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=f"W{index}",
        source_type=EvidenceSourceType.WEB,
        title=item.title,
        snippet=item.text[:600],
        url=item.url,
        source_id=item.source,
        score=item.score,
        meta={"text": item.text, "source": item.source},
    )


def _claim_verdict_from_llm(
    claim: ClassifiedClaim,
    evidence: list[EvidenceItem],
    payload: dict[str, Any],
) -> ClaimVerdict:
    return ClaimVerdict(
        claim=claim,
        verdict=_verdict_label(payload.get("verdict")),
        verification_stream=claim.verification_stream,
        confidence=_confidence(payload.get("confidence")),
        rationale=str(payload.get("summary") or payload.get("rationale") or ""),
        evidence=evidence,
        meta={
            "verified_by": _verified_by(claim.verification_stream),
            "raw_verdict": payload,
        },
    )


def _verdict_label(value: Any) -> VerdictLabel:
    normalized = str(value or "").strip().upper()
    if normalized in {"SUPPORTS", "TRUE"}:
        return VerdictLabel.SUPPORTS
    if normalized in {"REFUTES", "FALSE", "PARTLY_TRUE"}:
        return VerdictLabel.REFUTES
    return VerdictLabel.NOT_ENOUGH_INFO


def _confidence(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    normalized = str(value or "").strip().lower()
    return {"high": 0.9, "medium": 0.6, "low": 0.3}.get(normalized)


def _verified_by(stream: VerificationStream) -> str:
    if stream == VerificationStream.STRUCTURED:
        return "local_knowledge_database"
    if stream == VerificationStream.WEB:
        return "brave_search_web_evidence"
    if stream == VerificationStream.MIXED:
        return "local_knowledge_database_and_web_evidence"
    return "none"


def _aggregate_verdict(verdicts: list[ClaimVerdict]) -> VerdictLabel:
    checked = [item.verdict for item in verdicts]
    if not checked:
        return VerdictLabel.NOT_ENOUGH_INFO
    if any(item == VerdictLabel.REFUTES for item in checked):
        return VerdictLabel.REFUTES
    if all(item == VerdictLabel.SUPPORTS for item in checked):
        return VerdictLabel.SUPPORTS
    return VerdictLabel.NOT_ENOUGH_INFO


def _summary(verdicts: list[ClaimVerdict], unsupported: list[ClassifiedClaim]) -> str:
    supports = sum(1 for item in verdicts if item.verdict == VerdictLabel.SUPPORTS)
    refutes = sum(1 for item in verdicts if item.verdict == VerdictLabel.REFUTES)
    unknown = sum(1 for item in verdicts if item.verdict == VerdictLabel.NOT_ENOUGH_INFO)
    return (
        f"Checked {len(verdicts)} claim(s): {supports} supported, {refutes} refuted, "
        f"{unknown} not enough info. {len(unsupported)} claim(s) were unsupported or not checkable."
    )


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
