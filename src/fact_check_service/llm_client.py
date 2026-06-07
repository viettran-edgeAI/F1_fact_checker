from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from .config import FactCheckConfig
from .schemas import ClassifiedClaim, ExtractedClaim, VerificationStream


PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


class LLMClientError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, config: FactCheckConfig | None = None, client: httpx.Client | None = None) -> None:
        self.config = config or FactCheckConfig.from_env()
        self.client = client

    def extract_claims(self, text: str, *, max_claims: int = 8) -> list[ExtractedClaim]:
        payload = self._run_json_prompt("claim_extraction.md", {"input_text": text})
        claims = payload.get("claims", [])
        if not isinstance(claims, list):
            raise LLMClientError("Claim extraction returned invalid claims array.")

        extracted: list[ExtractedClaim] = []
        for index, item in enumerate(claims[:max_claims], start=1):
            if not isinstance(item, dict):
                continue
            claim_text = str(item.get("text") or item.get("claim") or "").strip()
            if not claim_text:
                continue
            extracted.append(
                ExtractedClaim(
                    claim_id=str(item.get("id") or item.get("claim_id") or f"C{index}"),
                    text=claim_text,
                    normalized_text=str(item.get("normalized_text") or claim_text),
                    source_text=text,
                    confidence=_float_or_none(item.get("confidence")),
                    meta={
                        "claim_type": item.get("claim_type"),
                        "route": item.get("route"),
                        "route_reason": item.get("route_reason"),
                        "requires_current_data": item.get("requires_current_data"),
                        "checkable": item.get("checkable"),
                    },
                )
            )
        return extracted

    def classify_claim(self, claim: ExtractedClaim, *, context: str = "") -> ClassifiedClaim:
        payload = self._run_json_prompt(
            "claim_classification.md",
            {"claim": claim.text, "context": context},
        )
        route = _route(payload.get("route") or payload.get("verification_stream"))
        entities = payload.get("structured_requirements", {}).get("entities", [])
        if not isinstance(entities, list):
            entities = []
        unsupported_reason = payload.get("unsupported_reason")
        return ClassifiedClaim(
            **claim.model_dump(),
            verification_stream=route,
            claim_type=str(payload.get("claim_type") or claim.meta.get("claim_type") or ""),
            entities=[str(entity) for entity in entities if entity],
            structured_query=_structured_query(claim, payload),
            unsupported_reason=str(unsupported_reason) if unsupported_reason else None,
        )

    def generate_search_query(self, claim: ClassifiedClaim, *, context: str = "") -> str:
        payload = self._run_json_prompt(
            "search_query_generation.md",
            {
                "claim": claim.model_dump_json(),
                "classification": claim.model_dump_json(),
                "context": context,
            },
        )
        queries = payload.get("queries", [])
        if isinstance(queries, list) and queries:
            first = queries[0]
            if isinstance(first, dict) and first.get("query"):
                return str(first["query"]).strip()
        return claim.text

    def generate_verdict(
        self,
        claim: ClassifiedClaim,
        *,
        structured_evidence: list[dict[str, Any]],
        web_evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self._run_json_prompt(
            "verdict_generation.md",
            {
                "claim": claim.model_dump_json(),
                "classification": claim.model_dump_json(),
                "structured_evidence": json.dumps(structured_evidence, ensure_ascii=False),
                "web_evidence": json.dumps(web_evidence, ensure_ascii=False),
            },
        )

    def _run_json_prompt(self, prompt_name: str, values: dict[str, str]) -> dict[str, Any]:
        prompt = _render_prompt(prompt_name, values)
        response = self._post_answer(prompt)
        return _parse_json_object(response)

    def _post_answer(self, prompt: str) -> str:
        payload = {"user_request": prompt, "thinking_mode": "fast", "max_tokens": 2048}
        if self.client is not None:
            response = self.client.post(f"{self.config.llm_service_url}/v1/answer", json=payload)
        else:
            with httpx.Client(timeout=self.config.llm_timeout_seconds) as client:
                response = client.post(f"{self.config.llm_service_url}/v1/answer", json=payload)
        response.raise_for_status()
        data = response.json()
        answer = data.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            raise LLMClientError("llm-service returned an empty answer.")
        return answer


def _render_prompt(prompt_name: str, values: dict[str, str]) -> str:
    path = PROMPT_DIR / prompt_name
    template = path.read_text(encoding="utf-8")
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if not match:
            raise LLMClientError("LLM response did not contain JSON.") from exc
        payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise LLMClientError("LLM response JSON must be an object.")
    return payload


def _route(value: Any) -> VerificationStream:
    try:
        return VerificationStream(str(value or "").lower())
    except ValueError:
        return VerificationStream.UNSUPPORTED


def _structured_query(claim: ExtractedClaim, payload: dict[str, Any]) -> str | None:
    parts = [claim.text]
    requirements = payload.get("structured_requirements")
    if isinstance(requirements, dict):
        for key in ("entities", "data_needed", "time_scope"):
            value = requirements.get(key)
            if isinstance(value, list):
                parts.extend(str(item) for item in value if item)
            elif value:
                parts.append(str(value))
    query = " ".join(parts).strip()
    return query or None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
