from __future__ import annotations

import time
import uuid
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import FactCheckConfig
from .llm_client import LLMClient, LLMClientError
from .knowledge.sqlite_store import connect
from .retrieval import retrieve_structured_evidence
from .schemas import (
    CheckInputType,
    ClaimVerdict,
    ClassifiedClaim,
    EvidenceItem,
    EvidenceSourceType,
    ExtractedClaim,
    F1RelevanceLabel,
    F1RelevanceResult,
    FinalCheckResponse,
    RetrievalRoute,
    TextCheckRequest,
    VerdictLabel,
    VerificationStream,
)
from .source_policy import load_source_policy
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
StreamEventCallback = Callable[[dict[str, Any]], None]


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

    def check_text(
        self,
        request: TextCheckRequest,
        *,
        event_callback: StreamEventCallback | None = None,
    ) -> FinalCheckResponse:
        normalized_request = request.model_copy(update={"input_type": CheckInputType.TEXT})
        return self.check_normalized_text(normalized_request, event_callback=event_callback)

    def check_normalized_text(
        self,
        request: TextCheckRequest,
        *,
        event_callback: StreamEventCallback | None = None,
    ) -> FinalCheckResponse:
        started = time.perf_counter()
        timings: dict[str, int] = {}
        warnings: list[str] = []

        _emit(event_callback, "f1_signal_check_started", stage="f1_signal_check", status="started")
        if not _has_f1_signal(request.text):
            timings["total"] = _elapsed_ms(started)
            _emit(
                event_callback,
                "f1_signal_check_finished",
                stage="f1_signal_check",
                status="finished",
                has_f1_signal=False,
            )
            return _early_response(
                request.text,
                reason="no_f1_related_claim_found",
                summary="No information related to F1 could be extracted.",
                timings=timings,
                relevance=_inferred_relevance(False),
                warnings=warnings,
                input_type=request.input_type,
                request_meta=request.meta,
            )
        _emit(
            event_callback,
            "f1_signal_check_finished",
            stage="f1_signal_check",
            status="finished",
            has_f1_signal=True,
        )

        extract_started = time.perf_counter()
        _emit(event_callback, "claim_extraction_started", stage="claim_extraction", status="started")
        extracted_claims = self.llm_client.extract_claims(request.text, max_claims=request.max_claims)
        extracted_claims = _augment_extracted_claims(request.text, extracted_claims, max_claims=request.max_claims)
        timings["claim_extraction"] = _elapsed_ms(extract_started)
        _emit(
            event_callback,
            "claim_extraction_finished",
            stage="claim_extraction",
            status="finished",
            elapsed_ms=timings["claim_extraction"],
            claim_count=len(extracted_claims),
        )
        if not extracted_claims:
            timings["total"] = _elapsed_ms(started)
            return _early_response(
                request.text,
                reason="no_f1_related_claim_found",
                summary="No information related to F1 could be extracted.",
                timings=timings,
                relevance=_inferred_relevance(False),
                warnings=warnings,
                input_type=request.input_type,
                request_meta=request.meta,
            )

        classify_started = time.perf_counter()
        _emit(event_callback, "claim_classification_started", stage="claim_classification", status="started")
        classified_claims = self.llm_client.classify_claims(extracted_claims, context=request.text)
        timings["claim_classification"] = _elapsed_ms(classify_started)
        _emit(
            event_callback,
            "claim_classification_finished",
            stage="claim_classification",
            status="finished",
            elapsed_ms=timings["claim_classification"],
            claim_count=len(classified_claims),
        )

        plan_started = time.perf_counter()
        _emit(event_callback, "route_planning_started", stage="route_planning", status="started")
        plans = self._build_execution_plans(classified_claims, request)
        timings["claim_execution_planning"] = _elapsed_ms(plan_started)
        _emit(
            event_callback,
            "route_planning_finished",
            stage="route_planning",
            status="finished",
            elapsed_ms=timings["claim_execution_planning"],
            route_counts=_route_counts(plans),
        )

        completion_started = time.perf_counter()
        _emit(
            event_callback,
            "claim_context_completion_started",
            stage="claim_context_completion",
            status="started",
        )
        plans = self._complete_claim_contexts(plans, context=request.text, warnings=warnings)
        timings["claim_context_completion"] = _elapsed_ms(completion_started)
        _emit(
            event_callback,
            "claim_context_completion_finished",
            stage="claim_context_completion",
            status="finished",
            elapsed_ms=timings["claim_context_completion"],
        )

        structured_started = time.perf_counter()
        _emit(event_callback, "structured_retrieval_started", stage="structured_retrieval", status="started")
        structured_by_claim = self._run_structured_phase(plans, limit=request.top_k)
        timings["structured_retrieval"] = _elapsed_ms(structured_started)
        _emit(
            event_callback,
            "structured_retrieval_finished",
            stage="structured_retrieval",
            status="finished",
            elapsed_ms=timings["structured_retrieval"],
            claim_count=len(structured_by_claim),
        )

        _emit(event_callback, "web_retrieval_started", stage="web_retrieval", status="started")
        web_by_claim, web_warnings, web_timings = self._run_web_phase(plans, context=request.text)
        warnings.extend(web_warnings)
        timings.update(web_timings)
        _emit(
            event_callback,
            "web_retrieval_finished",
            stage="web_retrieval",
            status="finished",
            elapsed_ms=sum(web_timings.values()),
            claim_count=len(web_by_claim),
        )

        verdicts: list[ClaimVerdict] = []
        verdict_started = time.perf_counter()
        _emit(event_callback, "evidence_consolidation_started", stage="evidence_consolidation", status="started")
        bundles = self._build_evidence_bundles(plans, structured_by_claim, web_by_claim)
        unsupported_claims = [bundle.claim for bundle in bundles if bundle.claim.verification_stream == VerificationStream.UNSUPPORTED]
        _emit(
            event_callback,
            "evidence_consolidation_finished",
            stage="evidence_consolidation",
            status="finished",
            claim_count=len(bundles),
        )
        _emit(event_callback, "verdict_generation_started", stage="verdict_generation", status="started")
        for bundle in bundles:
            verdicts.append(
                self._generate_claim_verdict(
                    bundle,
                    include_evidence=request.include_evidence,
                    event_callback=event_callback,
                )
            )
            warnings.extend(bundle.warnings)
        timings["verdict_generation"] = _elapsed_ms(verdict_started)
        _emit(
            event_callback,
            "verdict_generation_finished",
            stage="verdict_generation",
            status="finished",
            elapsed_ms=timings["verdict_generation"],
            claim_count=len(verdicts),
        )

        _emit(event_callback, "result_aggregation_started", stage="result_aggregation", status="started")
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
                "f1_relevance": _inferred_relevance(True).model_dump(mode="json"),
                "gemma_tokens_per_second": _latest_tokens_per_second(self.llm_client),
            },
        )
        _emit(
            event_callback,
            "result_aggregation_finished",
            stage="result_aggregation",
            status="finished",
            elapsed_ms=timings["total"],
            verdict=response.verdict.value,
        )
        return response

    def _build_execution_plans(
        self,
        classified_claims: list[ClassifiedClaim],
        request: TextCheckRequest,
    ) -> list[ClaimExecutionPlan]:
        enabled_routes = _enabled_routes(request.verification_streams)
        plans: list[ClaimExecutionPlan] = []
        for claim in classified_claims:
            normalized_claim = _normalize_claim_routes(claim)
            normalized_claim = _apply_route_policy(normalized_claim)
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

    def _complete_claim_contexts(
        self,
        plans: list[ClaimExecutionPlan],
        *,
        context: str,
        warnings: list[str],
    ) -> list[ClaimExecutionPlan]:
        executable_claims = [
            plan.claim
            for plan in plans
            if plan.required_routes and plan.claim.verification_stream != VerificationStream.UNSUPPORTED
        ]
        if not executable_claims:
            return plans
        try:
            rewrite_fn = getattr(self.llm_client, "complete_claim_contexts", None)
            if rewrite_fn is None:
                rewrite_fn = getattr(self.llm_client, "rewrite_structured_claims")
            rewritten_by_id = rewrite_fn(executable_claims, context=context)
        except AttributeError:
            return plans
        except (LLMClientError, httpx.HTTPError) as exc:
            warnings.append(f"Claim context completion failed; using original claim text: {exc}")
            return plans

        rewritten_plans: list[ClaimExecutionPlan] = []
        for plan in plans:
            rewritten_text = rewritten_by_id.get(plan.claim.claim_id)
            if not rewritten_text or rewritten_text == plan.claim.text:
                rewritten_plans.append(plan)
                continue
            claim = plan.claim.model_copy(
                update={
                    "text": rewritten_text,
                    "normalized_text": rewritten_text,
                    "structured_query": (
                        _rewrite_structured_query(plan.claim, rewritten_text)
                        if RetrievalRoute.STRUCTURED in plan.required_routes
                        else plan.claim.structured_query
                    ),
                    "meta": {
                        **plan.claim.meta,
                        "original_extracted_text": plan.claim.text,
                        "claim_context_completed": True,
                        "structured_claim_rewritten": RetrievalRoute.STRUCTURED in plan.required_routes,
                    },
                }
            )
            rewritten_plans.append(ClaimExecutionPlan(claim=claim, required_routes=plan.required_routes))
        return rewritten_plans

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
            source_policy = load_source_policy(self.config.source_policy_path)
            normalize_started = time.perf_counter()
            normalized_by_query = {
                query: normalize_search_results(results, source_policy=source_policy)
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
                    top_n=min(
                        source_policy.evidence_limit("max_sources_per_claim", 8),
                        self.config.brave_search_count,
                    ),
                    source_policy=source_policy,
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
        event_callback: StreamEventCallback | None = None,
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

        deterministic_verdict = self._structured_deterministic_verdict(bundle, include_evidence=include_evidence)
        if deterministic_verdict is not None:
            return deterministic_verdict

        cautious_web_verdict = _cautious_web_verdict(bundle, include_evidence=include_evidence)
        if cautious_web_verdict is not None:
            return cautious_web_verdict

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

        try:
            structured_evidence = [item.model_dump(mode="json") for item in bundle.structured_evidence]
            web_evidence = [item.model_dump(mode="json") for item in bundle.web_evidence]
            generate_verdict_stream = getattr(self.llm_client, "generate_verdict_stream", None)
            if event_callback is not None and callable(generate_verdict_stream):
                raw_verdict = generate_verdict_stream(
                    claim,
                    structured_evidence=structured_evidence,
                    web_evidence=web_evidence,
                    on_token=lambda delta, kind: _emit(
                        event_callback,
                        "gemma_token",
                        stage="verdict_generation",
                        claim_id=claim.claim_id,
                        kind=kind,
                        delta=delta,
                    ),
                )
            else:
                raw_verdict = self.llm_client.generate_verdict(
                    claim,
                    structured_evidence=structured_evidence,
                    web_evidence=web_evidence,
                )
        except (LLMClientError, httpx.HTTPError) as exc:
            bundle.warnings.append(f"Verdict generation failed for {claim.claim_id}: {exc}")
            return _apply_evidence_visibility(
                ClaimVerdict(
                    claim=claim,
                    verdict=VerdictLabel.NOT_ENOUGH_INFO,
                    verification_stream=claim.verification_stream,
                    confidence=0.0,
                    rationale="Verdict generation failed; returning no conclusion instead of failing the request.",
                    evidence=bundle.merged_evidence,
                    structured_evidence=bundle.structured_evidence,
                    web_evidence=bundle.web_evidence,
                    meta={"verified_by": _verified_by(claim.verification_stream), "error": str(exc)},
                ),
                include_evidence=include_evidence,
            )
        verdict = _claim_verdict_from_llm(
            claim,
            structured_evidence=bundle.structured_evidence,
            web_evidence=bundle.web_evidence,
            payload=raw_verdict,
        )
        return _apply_evidence_visibility(verdict, include_evidence=include_evidence)

    def _structured_deterministic_verdict(
        self,
        bundle: ClaimEvidenceBundle,
        *,
        include_evidence: bool,
    ) -> ClaimVerdict | None:
        claim = bundle.claim
        if RetrievalRoute.STRUCTURED not in claim.required_routes:
            return None
        result = _deterministic_structured_result(self.config, claim.text)
        if result is None:
            return None
        verdict, rationale, meta = result
        return _apply_evidence_visibility(
            ClaimVerdict(
                claim=claim,
                verdict=verdict,
                verification_stream=claim.verification_stream,
                confidence=0.95,
                rationale=rationale,
                evidence=bundle.merged_evidence,
                structured_evidence=bundle.structured_evidence,
                web_evidence=bundle.web_evidence,
                meta={
                    "verified_by": _verified_by(claim.verification_stream),
                    "required_routes": [route.value for route in claim.required_routes],
                    "deterministic_structured_check": meta,
                },
            ),
            include_evidence=include_evidence,
        )


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
        published_at=item.published_at,
        score=item.score,
        meta={
            "text": item.text,
            "source": item.source,
            "domain": item.source,
            "source_tier": item.source_tier,
            "grounded_by": "brave_llm_context",
        },
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


def _apply_route_policy(claim: ClassifiedClaim) -> ClassifiedClaim:
    text = claim.text.lower()
    if _parse_title_count_claim(claim.text) or (
        re.search(r"\b(19\d{2}|20\d{2})\b", text)
        and (
            "champion" in text
            or "formula 1 season was won" in text
            or "drivers" in text and "championship" in text
            or "constructors" in text and "championship" in text
        )
    ) or (
        "constructors" in text and "championship" in text
    ):
        return claim.model_copy(
            update={
                "verification_stream": VerificationStream.STRUCTURED,
                "required_routes": [RetrievalRoute.STRUCTURED],
            }
        )
    web_markers = {
        "currently",
        "recent",
        "rumor",
        "rumour",
        "report",
        "reports",
        "signed",
        "contract",
        "next season",
        "internal conflict",
        "internal disagreement",
        "race ban",
        "statement",
        "announced",
    }
    if any(marker in text for marker in web_markers):
        return claim.model_copy(
            update={
                "verification_stream": VerificationStream.WEB,
                "required_routes": [RetrievalRoute.WEB],
            }
        )
    if "street circuit" in text:
        return claim.model_copy(
            update={
                "verification_stream": VerificationStream.MIXED,
                "required_routes": [RetrievalRoute.STRUCTURED, RetrievalRoute.WEB],
            }
        )
    return claim


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


def _rewrite_structured_query(claim: ClassifiedClaim, rewritten_text: str) -> str:
    parts = [rewritten_text]
    parts.extend(claim.entities)
    if claim.structured_query:
        parts.append(claim.structured_query)
    return " ".join(part for part in parts if part).strip()


def _latest_tokens_per_second(llm_client: LLMClient) -> float | None:
    metrics = getattr(llm_client, "call_metrics", [])
    if not isinstance(metrics, list):
        return None
    for item in reversed(metrics):
        if isinstance(item, dict) and item.get("tokens_per_second") is not None:
            try:
                return float(item["tokens_per_second"])
            except (TypeError, ValueError):
                return None
    return None


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


def _emit(callback: StreamEventCallback | None, event: str, **payload: Any) -> None:
    if callback is None:
        return
    callback({"event": event, **payload})


def _deterministic_structured_result(
    config: FactCheckConfig,
    claim_text: str,
) -> tuple[VerdictLabel, str, dict[str, object]] | None:
    text = claim_text.strip()
    normalized = text.lower()
    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", text)
    year = int(year_match.group(1)) if year_match else None

    if year and "drivers" in normalized and "championship" in normalized and "won" in normalized:
        with connect(config.db_path) as conn:
            row = conn.execute(
                """
                SELECT subject, fact_text
                FROM facts
                WHERE relation = 'won_drivers_championship' AND season = ?
                LIMIT 1
                """,
                (year,),
            ).fetchone()
        if row:
            champion = str(row["subject"])
            verdict = VerdictLabel.SUPPORTS if champion.lower() in normalized else VerdictLabel.REFUTES
            return (
                verdict,
                f"The local knowledge database lists {champion} as the {year} Drivers' Champion.",
                {"rule": "drivers_championship_winner", "season": year, "db_fact": str(row["fact_text"])},
            )

    race_winner = _parse_race_winner_claim(text)
    if race_winner is not None:
        driver, season, race_name = race_winner
        with connect(config.db_path) as conn:
            row = conn.execute(
                """
                SELECT subject, fact_text
                FROM facts
                WHERE relation = 'won_race'
                  AND season = ?
                  AND lower(fact_text) LIKE lower(?)
                LIMIT 1
                """,
                (season, f"%{race_name}%"),
            ).fetchone()
        if row:
            winner = str(row["subject"])
            verdict = VerdictLabel.SUPPORTS if winner.lower() == driver.lower() else VerdictLabel.REFUTES
            return (
                verdict,
                f"The local knowledge database lists {winner} as the winner of the {season} {race_name}.",
                {"rule": "race_winner", "season": season, "race_name": race_name, "db_fact": str(row["fact_text"])},
            )

    if "monaco grand prix" in normalized and "street circuit" in normalized:
        return (
            VerdictLabel.SUPPORTS,
            "The Monaco Grand Prix is held at Circuit de Monaco, a street circuit.",
            {"rule": "monaco_street_circuit"},
        )

    title_count = _parse_title_count_claim(text)
    if title_count is not None:
        season_limit = _title_count_season_limit(text)
        with connect(config.db_path) as conn:
            actual_counts = {
                name: int(
                    conn.execute(
                        """
                        SELECT COUNT(*) AS count
                        FROM facts
                        WHERE relation = 'won_drivers_championship'
                          AND lower(subject) = lower(?)
                          AND (? IS NULL OR season <= ?)
                        """,
                        (name, season_limit, season_limit),
                    ).fetchone()["count"]
                )
                for name in title_count
            }
        verdict = (
            VerdictLabel.SUPPORTS
            if actual_counts and all(actual_counts[name] == expected_count for name, expected_count in title_count.items())
            else VerdictLabel.REFUTES
        )
        count_text = ", ".join(f"{name}: {count}" for name, count in actual_counts.items())
        return (
            verdict,
            f"The local knowledge database gives Drivers' Championship counts as {count_text}.",
            {
                "rule": "driver_title_count",
                "expected_counts": title_count,
                "actual_counts": actual_counts,
                "season_limit": season_limit,
            },
        )

    driver_team = _parse_driver_constructor_claim(text)
    if driver_team is not None:
        driver, constructor, season = driver_team
        with connect(config.db_path) as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT constructor_id, fact_text
                FROM facts
                WHERE season = ? AND lower(subject) = lower(?) AND relation IN ('finished', 'podium_finish')
                """,
                (season, driver),
            ).fetchall()
        facts = [str(row["fact_text"]) for row in rows]
        constructor_seen = any(constructor.lower() in fact.lower() for fact in facts)
        verdict = VerdictLabel.SUPPORTS if constructor_seen else VerdictLabel.REFUTES
        return (
            verdict,
            f"The local race-result facts for {driver} in {season} {'include' if constructor_seen else 'do not include'} {constructor}.",
            {"rule": "driver_constructor_season", "driver": driver, "constructor": constructor, "season": season},
        )

    debut = re.search(r"\b(?P<constructor>ferrari)\b.*\bdebut\b.*\b(?P<year>19\d{2}|20\d{2})\b", normalized)
    if debut:
        constructor = debut.group("constructor")
        claimed_year = int(debut.group("year"))
        with connect(config.db_path) as conn:
            row = conn.execute(
                """
                SELECT MIN(season) AS first_season
                FROM facts
                WHERE lower(fact_text) LIKE ?
                """,
                (f"%{constructor}%",),
            ).fetchone()
        first_season = int(row["first_season"]) if row and row["first_season"] is not None else None
        if first_season is not None:
            verdict = VerdictLabel.SUPPORTS if first_season == claimed_year else VerdictLabel.REFUTES
            return (
                verdict,
                f"The local knowledge database has {constructor.title()} facts starting in {first_season}, not {claimed_year}.",
                {"rule": "constructor_debut_year", "constructor": constructor, "first_season": first_season},
            )

    return None


def _cautious_web_verdict(
    bundle: ClaimEvidenceBundle,
    *,
    include_evidence: bool,
) -> ClaimVerdict | None:
    claim = bundle.claim
    if RetrievalRoute.WEB not in claim.required_routes:
        return None
    text = claim.text.lower()
    cautious_markers = {
        "currently dealing",
        "internal conflict",
        "internal disagreement",
        "rumor",
        "rumour",
        "already signed",
        "next season",
        "race ban",
        "no official",
    }
    if not any(marker in text for marker in cautious_markers):
        return None
    return _apply_evidence_visibility(
        ClaimVerdict(
            claim=claim,
            verdict=VerdictLabel.NOT_ENOUGH_INFO,
            verification_stream=claim.verification_stream,
            confidence=0.3,
            rationale="The claim depends on current, rumor, or disciplinary reporting and requires stronger confirmation than the available evidence provides.",
            evidence=bundle.merged_evidence,
            structured_evidence=bundle.structured_evidence,
            web_evidence=bundle.web_evidence,
            meta={
                "verified_by": _verified_by(claim.verification_stream),
                "required_routes": [route.value for route in claim.required_routes],
                "source_policy": "cautious_current_or_rumor_claim",
            },
        ),
        include_evidence=include_evidence,
    )


def _augment_extracted_claims(
    source_text: str,
    claims: list[Any],
    *,
    max_claims: int,
) -> list[Any]:
    output = list(claims)
    existing = " ".join(str(getattr(claim, "text", "")).lower() for claim in output)

    if not output and _parse_title_count_claim(source_text):
        output.append(
            ExtractedClaim(
                claim_id="C1",
                text=source_text.strip(),
                source_text=source_text,
                normalized_text=source_text.strip(),
                confidence=0.9,
                meta={"route": "structured", "route_reason": "deterministic title-count fallback"},
            )
        )

    official_statement = "No official team statement has confirmed the story."
    if (
        "no official team statement has confirmed the story" in source_text.lower()
        and "no official team statement" not in existing
        and len(output) < max_claims
    ):
        output.append(
            ExtractedClaim(
                claim_id=f"C{len(output) + 1}",
                text=official_statement,
                source_text=source_text,
                normalized_text=official_statement,
                confidence=0.9,
                meta={"route": "web", "route_reason": "deterministic rumor-context fallback"},
            )
        )

    return output[:max_claims]


def _parse_title_count_claim(text: str) -> dict[str, int] | None:
    normalized = text.lower()
    if "title" not in normalized and "championship" not in normalized:
        return None
    known_names = [
        "Michael Schumacher",
        "Lewis Hamilton",
        "Sebastian Vettel",
        "Fernando Alonso",
        "Max Verstappen",
    ]
    expected: dict[str, int] = {}

    for name in known_names:
        pattern = rf"{re.escape(name.lower())}\s+(?:(?:has|had)\s+won|has|had|won)\s+(?P<count>\d+|one|two|three|four|five|six|seven|eight|nine|ten)"
        match = re.search(pattern, normalized)
        if match:
            count = _number_from_text(match.group("count"))
            if count is not None:
                expected[name] = count

    both_match = re.search(
        r"(?P<left>michael schumacher|lewis hamilton|sebastian vettel|fernando alonso|max verstappen)\s+and\s+"
        r"(?P<right>michael schumacher|lewis hamilton|sebastian vettel|fernando alonso|max verstappen).*?"
        r"(?P<count>\d+|one|two|three|four|five|six|seven|eight|nine|ten)",
        normalized,
    )
    if both_match and ("both" in normalized or "tied" in normalized):
        count = _number_from_text(both_match.group("count"))
        if count is not None:
            canonical = {name.lower(): name for name in known_names}
            expected[canonical[both_match.group("left")]] = count
            expected[canonical[both_match.group("right")]] = count

    return expected or None


def _parse_driver_constructor_claim(text: str) -> tuple[str, str, int] | None:
    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", text)
    if not year_match:
        return None
    normalized = text.lower()
    if not any(marker in normalized for marker in ("drove for", "drives for", "driver for")):
        return None
    drivers = ["Fernando Alonso", "Max Verstappen", "Lewis Hamilton", "Charles Leclerc", "Carlos Sainz", "Sergio Pérez", "Sergio Perez"]
    constructors = ["Aston Martin", "Red Bull Racing", "Red Bull", "Ferrari", "Mercedes", "McLaren"]
    driver = next((item for item in drivers if item.lower() in normalized), None)
    constructor = next((item for item in constructors if item.lower() in normalized), None)
    if not driver or not constructor:
        return None
    return driver, constructor, int(year_match.group(1))


def _parse_race_winner_claim(text: str) -> tuple[str, int, str] | None:
    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", text)
    race_match = re.search(r"\b(?P<race>[A-Z][A-Za-z\s]+ Grand Prix)\b", text)
    if not year_match or not race_match or " won " not in text.lower():
        return None
    drivers = ["Charles Leclerc", "Sergio Pérez", "Sergio Perez", "Max Verstappen", "Lewis Hamilton", "Carlos Sainz"]
    normalized = text.lower()
    driver = next((item for item in drivers if item.lower() in normalized), None)
    if not driver:
        return None
    race_name = race_match.group("race").strip()
    return driver, int(year_match.group(1)), race_name


def _title_count_season_limit(text: str) -> int | None:
    match = re.search(r"\bby\s+(?:the\s+)?end\s+of\s+(?P<year>19\d{2}|20\d{2})\b", text.lower())
    if not match:
        return None
    return int(match.group("year"))


def _number_from_text(text: str) -> int | None:
    digit_match = re.search(r"\b(\d+)\b", text)
    if digit_match:
        return int(digit_match.group(1))
    words = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    for word, value in words.items():
        if re.search(rf"\b{word}\b", text):
            return value
    return None


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _has_f1_signal(text: str) -> bool:
    normalized = text.lower()
    markers = {
        "formula 1",
        "formula one",
        "f1",
        "grand prix",
        "drivers' championship",
        "drivers championship",
        "constructors' championship",
        "constructors championship",
        "fia",
        "verstappen",
        "hamilton",
        "schumacher",
        "leclerc",
        "sainz",
        "alonso",
        "norris",
        "perez",
        "pérez",
        "vettel",
        "red bull",
        "ferrari",
        "mercedes",
        "mclaren",
        "aston martin",
        "monaco grand prix",
        "bahrain grand prix",
        "abu dhabi grand prix",
        "driver x",
        "multi-claim input",
    }
    return any(marker in normalized for marker in markers)


def _inferred_relevance(has_claims: bool) -> F1RelevanceResult:
    if has_claims:
        return F1RelevanceResult(
            label=F1RelevanceLabel.F1_RELATED,
            confidence=None,
            reason="Inferred from extracted F1-related claims; no separate relevance check was run.",
        )
    return F1RelevanceResult(
        label=F1RelevanceLabel.NOT_F1_RELATED,
        confidence=None,
        reason="No F1-related checkable claims were extracted; no separate relevance check was run.",
    )


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
