from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from runtime_env import load_env_file
from fact_check_service.orchestrator import FactCheckOrchestrator
from fact_check_service.schemas import FinalCheckResponse, TextCheckRequest


DEFAULT_CASES = ROOT / "tests" / "f1_fact_check_test_cases.jsonl"
DEFAULT_REPORT_DIR = ROOT / "data" / "fact_check" / "results"
DEFAULT_LLM_URL = "http://localhost:8081"


def main() -> int:
    args = parse_args()
    configure_environment(args)
    cases = filter_cases(load_cases(args.cases), args)
    runner = PipelineRunner(endpoint=args.endpoint)

    results: list[dict[str, Any]] = []
    for case in cases:
        result = run_case(
            case,
            runner=runner,
            max_claims=args.max_claims,
            top_k=args.top_k,
            include_evidence=not args.no_evidence,
        )
        results.append(result)
        print(format_console_result(result), flush=True)

    write_reports(results, args.report_dir)
    summary = summarize(results)
    print(
        "summary "
        + " ".join(f"{key}={summary.get(key, 0)}" for key in ("pass", "warn", "fail", "skip", "error"))
    )

    if any(result["status"] == "error" for result in results):
        return 2
    if args.fail_on_mismatch and any(result["status"] in {"fail", "warn"} for result in results):
        return 1
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run F1 fact-check JSONL cases through the current pipeline.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--ids", default="", help="Comma-separated case IDs to run.")
    parser.add_argument("--include-web", action="store_true", help="Include cases whose expected route uses web/mixed.")
    parser.add_argument("--exclude-web", action="store_true", help="Skip web/mixed cases. This is the default.")
    parser.add_argument(
        "--group",
        choices=("all", "structured", "non_f1", "web"),
        default="all",
        help="Optional coarse case group filter.",
    )
    parser.add_argument("--fail-on-mismatch", action="store_true")
    parser.add_argument("--max-claims", type=int, default=None)
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--no-evidence", action="store_true")
    parser.add_argument("--endpoint", default="", help="Optional fact-check HTTP endpoint, e.g. http://localhost:8082.")
    parser.add_argument("--llm-url", default="", help="LLM service URL for direct orchestrator mode.")
    return parser.parse_args()


def configure_environment(args: argparse.Namespace) -> None:
    load_env_file(ROOT / ".env")
    load_env_file(ROOT / "configs" / "models.host.env")
    if args.llm_url:
        os.environ["LLM_SERVICE_URL"] = args.llm_url.rstrip("/")
    elif "LLM_SERVICE_URL" not in os.environ:
        os.environ["LLM_SERVICE_URL"] = DEFAULT_LLM_URL


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSONL row") from exc
        if not isinstance(payload, dict) or not payload.get("id") or not payload.get("input_text"):
            raise ValueError(f"{path}:{line_number}: case must contain id and input_text")
        cases.append(payload)
    return cases


def filter_cases(cases: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    selected_ids = {item.strip() for item in args.ids.split(",") if item.strip()}
    output: list[dict[str, Any]] = []
    for case in cases:
        if selected_ids and str(case["id"]) not in selected_ids:
            continue
        if args.group != "all" and case_group(case) != args.group:
            continue
        if not args.include_web and case_uses_web(case):
            output.append(skipped_case(case, "web case skipped; pass --include-web to run it"))
            continue
        output.append(case)
    return output


def case_group(case: dict[str, Any]) -> str:
    if str(case.get("expected_relevance")) == "non_f1":
        return "non_f1"
    if case_uses_web(case):
        return "web"
    return "structured"


def case_uses_web(case: dict[str, Any]) -> bool:
    routes = {str(route).lower() for route in case.get("expected_routes", [])}
    return bool(routes & {"web", "mixed"})


def skipped_case(case: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "__skip__": True,
        "id": case["id"],
        "case": case,
        "reason": reason,
    }


class PipelineRunner:
    def __init__(self, *, endpoint: str = "") -> None:
        self.endpoint = endpoint.rstrip("/")
        self._orchestrator: FactCheckOrchestrator | None = None

    def check_text(self, request: TextCheckRequest) -> FinalCheckResponse:
        if self.endpoint:
            with httpx.Client(timeout=300.0) as client:
                response = client.post(f"{self.endpoint}/v1/check/text", json=request.model_dump(mode="json"))
                response.raise_for_status()
                return FinalCheckResponse.model_validate(response.json())
        if self._orchestrator is None:
            self._orchestrator = FactCheckOrchestrator.from_env()
        return self._orchestrator.check_text(request)


def run_case(
    case: dict[str, Any],
    *,
    runner: PipelineRunner,
    max_claims: int | None,
    top_k: int | None,
    include_evidence: bool,
) -> dict[str, Any]:
    if case.get("__skip__"):
        return skipped_result(case["case"], str(case["reason"]))

    started = time.perf_counter()
    try:
        request = TextCheckRequest(
            text=str(case["input_text"]),
            max_claims=max_claims or int(case.get("expected_claim_count") or 8) or 8,
            top_k=top_k or 8,
            include_evidence=include_evidence,
            meta={"case_id": case["id"], "case_input_type": case.get("input_type", "")},
        )
        response = runner.check_text(request)
        actual = extract_actual(response)
        evaluation = evaluate_case(case, actual)
        status = status_from_evaluation(evaluation)
        return {
            "id": case["id"],
            "status": status,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "expected": expected_payload(case),
            "actual": actual,
            "mismatches": evaluation["mismatches"],
            "warnings": evaluation["warnings"],
            "runtime_error": None,
        }
    except Exception as exc:  # noqa: BLE001 - report runner must keep moving through cases.
        return {
            "id": case["id"],
            "status": "error",
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "expected": expected_payload(case),
            "actual": {},
            "mismatches": [],
            "warnings": [],
            "runtime_error": {"type": type(exc).__name__, "message": str(exc)},
        }


def expected_payload(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "relevance": case.get("expected_relevance"),
        "claim_count": case.get("expected_claim_count"),
        "routes": case.get("expected_routes", []),
        "verdict": case.get("expected_verdict"),
    }


def extract_actual(response: FinalCheckResponse) -> dict[str, Any]:
    claims = []
    route_union: set[str] = set()
    for claim_verdict in response.claims:
        claim = claim_verdict.claim
        routes = [str(route.value if hasattr(route, "value") else route) for route in claim.required_routes]
        if not routes and claim.verification_stream.value == "mixed":
            routes = ["structured", "web"]
        route_union.update(routes)
        top_evidence = []
        for evidence in claim_verdict.evidence[:3]:
            top_evidence.append(
                {
                    "source_type": evidence.source_type.value,
                    "title": evidence.title,
                    "snippet": evidence.snippet[:300],
                    "url": evidence.url,
                    "score": evidence.score,
                }
            )
        claims.append(
            {
                "id": claim.claim_id,
                "text": claim.text,
                "verdict": claim_verdict.verdict.value,
                "verification_stream": claim.verification_stream.value,
                "required_routes": routes,
                "confidence": claim_verdict.confidence,
                "verified_by": claim_verdict.meta.get("verified_by"),
                "top_evidence": top_evidence,
            }
        )

    meta = response.meta
    relevance_payload = meta.get("f1_relevance") if isinstance(meta.get("f1_relevance"), dict) else {}
    actual_routes = sorted(route_union) if route_union else ["none"]
    return {
        "relevance": relevance_payload.get("label"),
        "claim_count": len(response.claims),
        "routes": actual_routes,
        "verdict": response.verdict.value,
        "reason": meta.get("reason"),
        "summary": response.summary,
        "claims": claims,
        "warnings": meta.get("warnings", []),
        "timings_ms": meta.get("timings_ms", {}),
    }


def evaluate_case(case: dict[str, Any], actual: dict[str, Any]) -> dict[str, list[str]]:
    mismatches: list[str] = []
    warnings: list[str] = []

    expected_relevance = str(case.get("expected_relevance") or "")
    if relevance_matches(expected_relevance, str(actual.get("relevance") or "")) is False:
        mismatches.append(f"relevance expected {expected_relevance}, got {actual.get('relevance')}")

    expected_count = int(case.get("expected_claim_count") or 0)
    actual_count = int(actual.get("claim_count") or 0)
    if actual_count != expected_count:
        mismatches.append(f"claim_count expected {expected_count}, got {actual_count}")

    expected_routes = [str(route).lower() for route in case.get("expected_routes", [])]
    if not routes_match(expected_routes, [str(route).lower() for route in actual.get("routes", [])]):
        mismatches.append(f"routes expected {expected_routes}, got {actual.get('routes')}")

    expected_verdict = str(case.get("expected_verdict") or "")
    if not verdict_matches(expected_verdict, actual):
        mismatches.append(f"verdict expected {expected_verdict}, got {actual.get('verdict')}")

    if actual_count and not any(claim.get("top_evidence") for claim in actual.get("claims", [])):
        warnings.append("no evidence returned for checked claims")

    return {"mismatches": mismatches, "warnings": warnings}


def relevance_matches(expected: str, actual: str) -> bool:
    expected_map = {"f1": "f1_related", "non_f1": "not_f1_related"}
    return expected_map.get(expected, expected) == actual


def routes_match(expected: list[str], actual: list[str]) -> bool:
    expected_set = set(expected)
    actual_set = set(actual)
    if expected_set == {"none"}:
        return actual_set == {"none"}
    if expected_set == {"mixed"}:
        return "mixed" in actual_set or {"structured", "web"}.issubset(actual_set)
    return expected_set == actual_set


def verdict_matches(expected: str, actual: dict[str, Any]) -> bool:
    verdict = str(actual.get("verdict") or "")
    reason = str(actual.get("reason") or "")
    claim_verdicts = {str(claim.get("verdict") or "") for claim in actual.get("claims", [])}
    if expected == "true":
        return verdict == "SUPPORTS"
    if expected == "false":
        return verdict == "REFUTES"
    if expected == "unsupported":
        return verdict == "NOT_ENOUGH_INFO"
    if expected == "not_f1":
        return verdict == "NOT_ENOUGH_INFO" and reason == "not_f1_related"
    if expected == "mixed":
        return len(claim_verdicts) > 1 or verdict in {"REFUTES", "NOT_ENOUGH_INFO"}
    return expected == verdict


def status_from_evaluation(evaluation: dict[str, list[str]]) -> str:
    if evaluation["mismatches"]:
        return "fail"
    if evaluation["warnings"]:
        return "warn"
    return "pass"


def skipped_result(case: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "id": case["id"],
        "status": "skip",
        "elapsed_ms": 0,
        "expected": expected_payload(case),
        "actual": {},
        "mismatches": [],
        "warnings": [reason],
        "runtime_error": None,
    }


def write_reports(results: list[dict[str, Any]], report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = report_dir / "f1_fact_check_jsonl_results.jsonl"
    summary_path = report_dir / "f1_fact_check_jsonl_summary.md"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    summary_path.write_text(render_markdown_summary(results), encoding="utf-8")
    print(f"wrote {jsonl_path}")
    print(f"wrote {summary_path}")


def render_markdown_summary(results: list[dict[str, Any]]) -> str:
    counts = summarize(results)
    lines = [
        "# F1 Fact Check JSONL Report",
        "",
        "## Totals",
        "",
        "| Status | Count |",
        "| --- | ---: |",
    ]
    for status in ("pass", "warn", "fail", "skip", "error"):
        lines.append(f"| {status} | {counts.get(status, 0)} |")

    lines.extend(["", "## Failures"])
    failed = [result for result in results if result["status"] in {"fail", "error"}]
    if not failed:
        lines.append("")
        lines.append("No failures.")
    for result in failed:
        reason = "; ".join(result.get("mismatches") or [])
        if result.get("runtime_error"):
            reason = f"{result['runtime_error']['type']}: {result['runtime_error']['message']}"
        lines.append(f"- `{result['id']}`: {reason}")

    lines.extend(["", "## Slowest Cases"])
    for result in sorted(results, key=lambda item: int(item.get("elapsed_ms") or 0), reverse=True)[:10]:
        lines.append(f"- `{result['id']}`: {result.get('elapsed_ms', 0)} ms ({result['status']})")
    lines.append("")
    return "\n".join(lines)


def summarize(results: list[dict[str, Any]]) -> Counter[str]:
    return Counter(str(result.get("status") or "unknown") for result in results)


def format_console_result(result: dict[str, Any]) -> str:
    if result["status"] == "error":
        error = result.get("runtime_error") or {}
        return f"{result['status']:>5} {result['id']} {error.get('type')}: {error.get('message')}"
    detail = "; ".join(result.get("mismatches") or result.get("warnings") or [])
    return f"{result['status']:>5} {result['id']} {detail}"


if __name__ == "__main__":
    raise SystemExit(main())
