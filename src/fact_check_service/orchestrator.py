from __future__ import annotations

import time
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import FactCheckConfig
from .llm_client import LLMClient
from .retrieval import retrieve_structured_evidence
from .schemas import (
    CheckInputType,
    ClaimVerdict,
    ClassifiedClaim,
    EvidenceItem,
    EvidenceSourceType,
    F1RelevanceLabel,
    F1RelevanceResult,
    FinalCheckResponse,
    RetrievalRoute,
    TextCheckRequest,
    VerdictLabel,
    VerificationStream,
)
from .web_evidence import (
    WebEvidence,
    fetch_article_texts,
    normalize_search_results,
    rank_evidence_candidates,
)
from .web_search import BraveSearchClient, BraveSearchError


StructuredRetriever = Callable[[ClassifiedClaim, int], list[dict[str, Any]]]
WebSearcher = Callable[[str, int], list[dict[str, Any]]]
WebEvidenceFetcher = Callable[[str, list[dict[str, Any]]], list[WebEvidence]]


@dataclass(slots=True)
class ClaimExecutionPlan:
    claim: ClassifiedClaim
    required_routes: tuple[RetrievalRoute, ...]


@dataclass(slots=True)
class ClaimEvidenceBundle:
    claim: ClassifiedClaim
    structured_evidence: list[EvidenceItem] = field(default_factory=list)
    web_evidence: list[EvidenceItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    search_query: str | None = None

    @property
    def merged_evidence(self) -> list[EvidenceItem]:
        return [*self.structured_evidence, *self.web_evidence]


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
        normalized_request = request.model_copy(update={"input_type": CheckInputType.TEXT})
        return self.check_normalized_text(normalized_request)

    def check_normalized_text(self, request: TextCheckRequest) -> FinalCheckResponse:
        started = time.perf_counter()
        timings: dict[str, int] = {}
        warnings: list[str] = []

        gate_response, relevance = self.apply_relevance_gate(
            request.text,
            input_type=request.input_type,
            request_meta=request.meta,
            started=started,
            timings=timings,
            warnings=warnings,
        )
        if gate_response is not None:
            return gate_response

        extract_started = time.perf_counter()
        extracted_claims = self.llm_client.extract_claims(request.text, max_claims=request.max_claims)
        timings["claim_extraction"] = _elapsed_ms(extract_started)
        if not extracted_claims:
            timings["total"] = _elapsed_ms(started)
            return _early_response(
                request.text,
                reason="no_checkable_claims",
                summary="F1-related content found, but no checkable claim detected.",
                timings=timings,
                relevance=relevance,
                warnings=warnings,
                input_type=request.input_type,
                request_meta=request.meta,
            )

        classify_started = time.perf_counter()
        classified_claims = self.llm_client.classify_claims(extracted_claims, context=request.text)
        timings["claim_classification"] = _elapsed_ms(classify_started)

        plan_started = time.perf_counter()
        plans = self._build_execution_plans(classified_claims, request)
        timings["claim_execution_planning"] = _elapsed_ms(plan_started)

        structured_started = time.perf_counter()
        structured_by_claim = self._run_structured_phase(plans, limit=request.top_k)
        timings["structured_retrieval"] = _elapsed_ms(structured_started)

        web_by_claim, web_warnings, web_timings = self._run_web_phase(plans, context=request.text)
        warnings.extend(web_warnings)
        timings.update(web_timings)

        verdicts: list[ClaimVerdict] = []
        verdict_started = time.perf_counter()
        bundles = self._build_evidence_bundles(plans, structured_by_claim, web_by_claim)
        unsupported_claims = [bundle.claim for bundle in bundles if bundle.claim.verification_stream == VerificationStream.UNSUPPORTED]
        for bundle in bundles:
            verdicts.append(self._generate_claim_verdict(bundle, include_evidence=request.include_evidence))
            warnings.extend(bundle.warnings)
        timings["verdict_generation"] = _elapsed_ms(verdict_started)

        timings["total"] = _elapsed_ms(started)
        response = FinalCheckResponse(
            text=request.text,
            verdict=_aggregate_verdict(verdicts),
            claims=verdicts,
            summary=_summary(verdicts, unsupported_claims),
            unsupported_claims=unsupported_claims,
            meta={
                **request.meta,
                "run_id": f"run_{uuid.uuid4().hex}",
                "input_type": request.input_type.value,
                "warnings": warnings,
                "timings_ms": timings,
                "route_counts": _route_counts(plans),
                "f1_relevance": relevance.model_dump(mode="json"),
            },
        )
        return response

    def apply_relevance_gate(
        self,
        text: str,
        *,
        input_type: CheckInputType = CheckInputType.TEXT,
        request_meta: dict[str, object] | None = None,
        started: float | None = None,
        timings: dict[str, int] | None = None,
        warnings: list[str] | None = None,
    ) -> tuple[FinalCheckResponse | None, F1RelevanceResult]:
        gate_started = started if started is not None else time.perf_counter()
        timing_payload = timings if timings is not None else {}
        warning_payload = warnings if warnings is not None else []

        relevance_started = time.perf_counter()
        relevance = self.llm_client.classify_f1_relevance(text)
        timing_payload["f1_relevance_classification"] = _elapsed_ms(relevance_started)

        if relevance.label != F1RelevanceLabel.NOT_F1_RELATED:
            return None, relevance

        timing_payload["total"] = _elapsed_ms(gate_started)
        return (
            _early_response(
                text,
                reason="not_f1_related",
                summary="This content is not related to Formula 1. No fact-check was performed.",
                timings=timing_payload,
                relevance=relevance,
                warnings=warning_payload,
                input_type=input_type,
                request_meta=request_meta or {},
            ),
            relevance,
        )

    def _build_execution_plans(
        self,
        classified_claims: list[ClassifiedClaim],
        request: TextCheckRequest,
    ) -> list[ClaimExecutionPlan]:
        enabled_routes = _enabled_routes(request.verification_streams)
        plans: list[ClaimExecutionPlan] = []
        for claim in classified_claims:
            normalized_claim = _normalize_claim_routes(claim)
            required_routes = tuple(normalized_claim.required_routes)
            if any(route not in enabled_routes for route in required_routes):
                normalized_claim = normalized_claim.model_copy(
                    update={
                        "verification_stream": VerificationStream.UNSUPPORTED,
                        "required_routes": [],
                        "unsupported_reason": "Verification route disabled for this request.",
                    }
                )
                required_routes = ()
            plans.append(ClaimExecutionPlan(claim=normalized_claim, required_routes=required_routes))
        return plans

    def _run_structured_phase(
        self,
        plans: list[ClaimExecutionPlan],
        *,
        limit: int,
    ) -> dict[str, list[EvidenceItem]]:
        retriever = self.structured_retriever or _default_structured_retriever
        evidence_by_claim: dict[str, list[EvidenceItem]] = {}
        for plan in plans:
            if RetrievalRoute.STRUCTURED not in plan.required_routes:
                continue
            rows = retriever(plan.claim, limit)
            evidence_by_claim[plan.claim.claim_id] = [
                _local_evidence_item(index, row) for index, row in enumerate(rows, start=1)
            ]
        return evidence_by_claim

    def _run_web_phase(
        self,
        plans: list[ClaimExecutionPlan],
        *,
        context: str,
    ) -> tuple[dict[str, list[EvidenceItem]], list[str], dict[str, int]]:
        timings: dict[str, int] = {}
        warnings: list[str] = []
        evidence_by_claim: dict[str, list[EvidenceItem]] = {}

        web_plans = [plan for plan in plans if RetrievalRoute.WEB in plan.required_routes]
        if not web_plans:
            timings["web_query_generation"] = 0
            timings["web_search"] = 0
            timings["web_article_fetch"] = 0
            timings["web_evidence_normalization"] = 0
            timings["web_evidence_ranking"] = 0
            return evidence_by_claim, warnings, timings

        query_started = time.perf_counter()
        queries_by_claim = self.llm_client.generate_search_queries([plan.claim for plan in web_plans], context=context)
        timings["web_query_generation"] = _elapsed_ms(query_started)

        query_to_claim_ids: dict[str, list[str]] = defaultdict(list)
        for plan in web_plans:
            query = (queries_by_claim.get(plan.claim.claim_id) or plan.claim.web_query_hint or plan.claim.text).strip()
            if not query:
                warnings.append(f"Web query generation returned no query for {plan.claim.claim_id}.")
                continue
            query_to_claim_ids[query].append(plan.claim.claim_id)

        searcher = self.web_searcher or _default_web_searcher(self.config)
        search_started = time.perf_counter()
        search_results_by_query: dict[str, list[dict[str, Any]]] = {}
        for query in query_to_claim_ids:
            try:
                search_results_by_query[query] = searcher(query, self.config.brave_search_count)
            except (BraveSearchError, httpx.HTTPError) as exc:
                warnings.append(f"Web evidence retrieval failed for query '{query}': {exc}")
                search_results_by_query[query] = []
        timings["web_search"] = _elapsed_ms(search_started)

        if self.web_evidence_fetcher is not None:
            fetch_started = time.perf_counter()
            ranked_by_query = {
                query: self.web_evidence_fetcher(query, results)
                for query, results in search_results_by_query.items()
            }
            timings["web_article_fetch"] = _elapsed_ms(fetch_started)
            timings["web_evidence_normalization"] = 0
            timings["web_evidence_ranking"] = 0
        else:
            normalize_started = time.perf_counter()
            normalized_by_query = {
                query: normalize_search_results(results)
                for query, results in search_results_by_query.items()
            }
            timings["web_evidence_normalization"] = _elapsed_ms(normalize_started)

            fetch_started = time.perf_counter()
            article_texts_by_query = {
                query: fetch_article_texts(results, timeout_seconds=self.config.brave_search_timeout)
                for query, results in normalized_by_query.items()
            }
            timings["web_article_fetch"] = _elapsed_ms(fetch_started)

            ranking_started = time.perf_counter()
            ranked_by_query = {
                query: rank_evidence_candidates(
                    query,
                    results,
                    article_texts_by_query.get(query, {}),
                    top_n=min(3, self.config.brave_search_count),
                )
                for query, results in normalized_by_query.items()
            }
            timings["web_evidence_ranking"] = _elapsed_ms(ranking_started)

        for query, claim_ids in query_to_claim_ids.items():
            ranked = ranked_by_query.get(query, [])
            items = [_web_evidence_item(index, item) for index, item in enumerate(ranked, start=1)]
            for claim_id in claim_ids:
                evidence_by_claim[claim_id] = [item.model_copy(deep=True) for item in items]

        return evidence_by_claim, warnings, timings

    def _build_evidence_bundles(
        self,
        plans: list[ClaimExecutionPlan],
        structured_by_claim: dict[str, list[EvidenceItem]],
        web_by_claim: dict[str, list[EvidenceItem]],
    ) -> list[ClaimEvidenceBundle]:
        bundles: list[ClaimEvidenceBundle] = []
        for plan in plans:
            bundles.append(
                ClaimEvidenceBundle(
                    claim=plan.claim,
                    structured_evidence=structured_by_claim.get(plan.claim.claim_id, []),
                    web_evidence=web_by_claim.get(plan.claim.claim_id, []),
                )
            )
        return bundles

    def _generate_claim_verdict(
        self,
        bundle: ClaimEvidenceBundle,
        *,
        include_evidence: bool,
    ) -> ClaimVerdict:
        claim = bundle.claim
        if claim.verification_stream == VerificationStream.UNSUPPORTED:
            return _apply_evidence_visibility(
                ClaimVerdict(
                    claim=claim,
                    verdict=VerdictLabel.NOT_ENOUGH_INFO,
                    verification_stream=VerificationStream.UNSUPPORTED,
                    confidence=0.0,
                    rationale=claim.unsupported_reason or "The claim is unsupported or not checkable as written.",
                    evidence=[],
                    structured_evidence=[],
                    web_evidence=[],
                    meta={"verified_by": "none"},
                ),
                include_evidence=include_evidence,
            )

        evidence = bundle.merged_evidence
        if not evidence:
            return _apply_evidence_visibility(
                ClaimVerdict(
                    claim=claim,
                    verdict=VerdictLabel.NOT_ENOUGH_INFO,
                    verification_stream=claim.verification_stream,
                    confidence=0.0,
                    rationale="No relevant evidence was found for this claim.",
                    evidence=[],
                    structured_evidence=[],
                    web_evidence=[],
                    meta={"verified_by": _verified_by(claim.verification_stream)},
                ),
                include_evidence=include_evidence,
            )

        raw_verdict = self.llm_client.generate_verdict(
            claim,
            structured_evidence=[item.model_dump(mode="json") for item in bundle.structured_evidence],
            web_evidence=[item.model_dump(mode="json") for item in bundle.web_evidence],
        )
        verdict = _claim_verdict_from_llm(
            claim,
            structured_evidence=bundle.structured_evidence,
            web_evidence=bundle.web_evidence,
            payload=raw_verdict,
        )
        return _apply_evidence_visibility(verdict, include_evidence=include_evidence)


def _default_structured_retriever(claim: ClassifiedClaim, limit: int) -> list[dict[str, Any]]:
    return retrieve_structured_evidence(
        {
            "claim": claim.structured_query or claim.text,
            "entities": {str(index): value for index, value in enumerate(claim.entities)},
            "verification_stream": "structured",
        },
        limit=limit,
    )


def _early_response(
    text: str,
    *,
    reason: str,
    summary: str,
    timings: dict[str, int],
    relevance: F1RelevanceResult,
    warnings: list[str],
    input_type: CheckInputType,
    request_meta: dict[str, object] | None = None,
) -> FinalCheckResponse:
    return FinalCheckResponse(
        text=text,
        verdict=VerdictLabel.NOT_ENOUGH_INFO,
        claims=[],
        summary=summary,
        unsupported_claims=[],
        meta={
            **(request_meta or {}),
            "run_id": f"run_{uuid.uuid4().hex}",
            "input_type": input_type.value,
            "reason": reason,
            "warnings": warnings,
            "timings_ms": timings,
            "f1_relevance": relevance.model_dump(mode="json"),
        },
    )


def _default_web_searcher(config: FactCheckConfig) -> WebSearcher:
    client = BraveSearchClient()

    def search(query: str, count: int) -> list[dict[str, Any]]:
        return client.llm_context(
            query,
            count=min(count, config.brave_context_count),
            max_urls=config.brave_context_max_urls,
            max_snippets=config.brave_context_max_snippets,
            max_tokens=config.brave_context_max_tokens,
        )

    return search


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
        meta={"text": item.text, "source": item.source, "grounded_by": "brave_llm_context"},
    )


def _claim_verdict_from_llm(
    claim: ClassifiedClaim,
    *,
    structured_evidence: list[EvidenceItem],
    web_evidence: list[EvidenceItem],
    payload: dict[str, Any],
) -> ClaimVerdict:
    evidence = [*structured_evidence, *web_evidence]
    return ClaimVerdict(
        claim=claim,
        verdict=_verdict_label(payload.get("verdict")),
        verification_stream=claim.verification_stream,
        confidence=_confidence(payload.get("confidence")),
        rationale=str(payload.get("summary") or payload.get("rationale") or ""),
        evidence=evidence,
        structured_evidence=structured_evidence,
        web_evidence=web_evidence,
        meta={
            "verified_by": _verified_by(claim.verification_stream),
            "required_routes": [route.value for route in claim.required_routes],
            "raw_verdict": payload,
        },
    )


def _enabled_routes(streams: list[VerificationStream]) -> set[RetrievalRoute]:
    enabled: set[RetrievalRoute] = set()
    if VerificationStream.STRUCTURED in streams or VerificationStream.MIXED in streams:
        enabled.add(RetrievalRoute.STRUCTURED)
    if VerificationStream.WEB in streams or VerificationStream.MIXED in streams:
        enabled.add(RetrievalRoute.WEB)
    return enabled


def _normalize_claim_routes(claim: ClassifiedClaim) -> ClassifiedClaim:
    if claim.required_routes:
        required_routes = list(dict.fromkeys(claim.required_routes))
    else:
        required_routes = _routes_for_stream(claim.verification_stream)
    return claim.model_copy(
        update={
            "required_routes": required_routes,
            "verification_stream": _stream_for_routes(required_routes, fallback=claim.verification_stream),
        }
    )


def _routes_for_stream(stream: VerificationStream) -> list[RetrievalRoute]:
    if stream == VerificationStream.STRUCTURED:
        return [RetrievalRoute.STRUCTURED]
    if stream == VerificationStream.WEB:
        return [RetrievalRoute.WEB]
    if stream == VerificationStream.MIXED:
        return [RetrievalRoute.STRUCTURED, RetrievalRoute.WEB]
    return []


def _stream_for_routes(
    routes: list[RetrievalRoute],
    *,
    fallback: VerificationStream = VerificationStream.UNSUPPORTED,
) -> VerificationStream:
    normalized = {route.value for route in routes}
    if normalized == {"structured"}:
        return VerificationStream.STRUCTURED
    if normalized == {"web"}:
        return VerificationStream.WEB
    if normalized == {"structured", "web"}:
        return VerificationStream.MIXED
    return fallback if not normalized else VerificationStream.UNSUPPORTED


def _apply_evidence_visibility(verdict: ClaimVerdict, *, include_evidence: bool) -> ClaimVerdict:
    if include_evidence:
        return verdict
    return verdict.model_copy(update={"evidence": [], "structured_evidence": [], "web_evidence": []})


def _route_counts(plans: list[ClaimExecutionPlan]) -> dict[str, int]:
    counts = {
        "structured": 0,
        "web": 0,
        "mixed": 0,
        "unsupported": 0,
    }
    for plan in plans:
        counts[plan.claim.verification_stream.value] = counts.get(plan.claim.verification_stream.value, 0) + 1
    return counts


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
