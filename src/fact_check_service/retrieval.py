from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .config import FactCheckConfig
from .knowledge.retrieval import search_facts
from .knowledge.sqlite_store import connect, initialize_schema


STRUCTURED_VERIFICATION_STREAM = "structured"
LOCAL_KNOWLEDGE_VERIFIER = "local_knowledge_database"


def structured_claim_query(claim: Mapping[str, Any] | str) -> str:
    """Build a local-knowledge search query from a structured claim payload."""
    if isinstance(claim, str):
        return claim

    parts: list[str] = []
    claim_text = claim.get("claim")
    if claim_text:
        parts.append(str(claim_text))

    entities = claim.get("entities")
    if isinstance(entities, Mapping):
        for value in entities.values():
            if value is None:
                continue
            parts.append(str(value))

    return " ".join(parts).strip()


def fact_to_evidence_item(fact: Mapping[str, Any]) -> dict[str, Any]:
    """Return an EvidenceItem-compatible dict while preserving raw fact fields."""
    evidence = dict(fact)
    evidence.setdefault("evidence_type", "local_fact")
    evidence.setdefault("verified_by", LOCAL_KNOWLEDGE_VERIFIER)
    evidence.setdefault("text", evidence.get("fact_text"))
    evidence.setdefault("title", evidence.get("fact_text"))
    evidence.setdefault("url", None)
    return evidence


def retrieve_structured_evidence(
    claim: Mapping[str, Any] | str,
    *,
    config: FactCheckConfig | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Retrieve local DB evidence for claims routed to the structured stream."""
    if isinstance(claim, Mapping) and claim.get("verification_stream") not in (None, STRUCTURED_VERIFICATION_STREAM):
        return []

    query = structured_claim_query(claim)
    if not query:
        return []

    resolved_config = config or FactCheckConfig.from_env()
    with connect(resolved_config.db_path) as conn:
        initialize_schema(conn)
        facts = search_facts(conn, query, limit=limit, config=resolved_config)

    return [fact_to_evidence_item(fact) for fact in facts]


def retrieve_evidence(
    claim: Mapping[str, Any] | str,
    *,
    config: FactCheckConfig | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Compatibility wrapper for structured local knowledge retrieval."""
    return retrieve_structured_evidence(claim, config=config, limit=limit)
