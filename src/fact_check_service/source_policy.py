from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml


APP_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_POLICY_PATH = APP_ROOT / "configs" / "source_policy.yaml"


@dataclass(frozen=True, slots=True)
class SourceTier:
    name: str
    trust_score: float
    verdict_strength: str
    domains: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourcePolicy:
    path: Path
    source_tiers: dict[str, SourceTier]
    blocked_domains: tuple[str, ...]
    ranking_weights: dict[str, float]
    evidence_limits: dict[str, int]
    brave_llm_context_defaults: dict[str, int]
    max_snippet_chars: int

    def tier_for_url(self, url: str) -> SourceTier:
        return self.tier_for_domain(normalize_domain(url))

    def tier_for_domain(self, domain: str) -> SourceTier:
        normalized = normalize_domain(domain)
        if self.is_blocked(normalized):
            return self.source_tiers.get("blocked", _fallback_tier("blocked", 0.0, "blocked"))
        for tier in self.source_tiers.values():
            if any(domain_matches(normalized, allowed_domain) for allowed_domain in tier.domains):
                return tier
        return self.source_tiers.get("unknown", _fallback_tier("unknown", 0.45, "low"))

    def is_blocked(self, domain_or_url: str) -> bool:
        normalized = normalize_domain(domain_or_url)
        return any(domain_matches(normalized, blocked) for blocked in self.blocked_domains)

    def weight(self, name: str, default: float) -> float:
        return float(self.ranking_weights.get(name, default))

    def evidence_limit(self, name: str, default: int) -> int:
        return int(self.evidence_limits.get(name, default))


def load_source_policy(path: Path | str | None = None) -> SourcePolicy:
    policy_path = Path(path) if path else DEFAULT_SOURCE_POLICY_PATH
    return _load_source_policy(str(policy_path))


@lru_cache(maxsize=8)
def _load_source_policy(path: str) -> SourcePolicy:
    policy_path = Path(path)
    payload = yaml.safe_load(policy_path.read_text(encoding="utf-8")) if policy_path.exists() else {}
    if not isinstance(payload, dict):
        payload = {}

    raw_tiers = payload.get("source_tiers")
    source_tiers: dict[str, SourceTier] = {}
    if isinstance(raw_tiers, dict):
        for name, raw_tier in raw_tiers.items():
            if not isinstance(raw_tier, dict):
                continue
            domains = raw_tier.get("domains")
            source_tiers[str(name)] = SourceTier(
                name=str(name),
                trust_score=_float(raw_tier.get("trust_score"), 0.45),
                verdict_strength=str(raw_tier.get("verdict_strength") or "low"),
                domains=tuple(normalize_domain(str(domain)) for domain in domains if domain) if isinstance(domains, list) else (),
            )

    source_tiers.setdefault("unknown", _fallback_tier("unknown", 0.45, "low"))
    source_tiers.setdefault("blocked", _fallback_tier("blocked", 0.0, "blocked"))

    ranking = payload.get("ranking")
    weights = ranking.get("weights") if isinstance(ranking, dict) and isinstance(ranking.get("weights"), dict) else {}
    evidence_limits = (
        ranking.get("evidence_limits")
        if isinstance(ranking, dict) and isinstance(ranking.get("evidence_limits"), dict)
        else {}
    )
    prompt_export = payload.get("prompt_export") if isinstance(payload.get("prompt_export"), dict) else {}
    brave_defaults = payload.get("brave_llm_context_defaults")

    return SourcePolicy(
        path=policy_path,
        source_tiers=source_tiers,
        blocked_domains=tuple(
            normalize_domain(str(domain))
            for domain in payload.get("blocked_domains", [])
            if isinstance(domain, str) and domain.strip()
        )
        if isinstance(payload.get("blocked_domains"), list)
        else (),
        ranking_weights={str(key): _float(value, 0.0) for key, value in weights.items()} if isinstance(weights, dict) else {},
        evidence_limits={
            str(key): int(value)
            for key, value in evidence_limits.items()
            if isinstance(value, int) or (isinstance(value, str) and value.isdigit())
        }
        if isinstance(evidence_limits, dict)
        else {},
        brave_llm_context_defaults={
            str(key): int(value)
            for key, value in brave_defaults.items()
            if isinstance(value, int) or (isinstance(value, str) and value.isdigit())
        }
        if isinstance(brave_defaults, dict)
        else {},
        max_snippet_chars=int(prompt_export.get("max_snippet_chars") or 1200),
    )


def normalize_domain(domain_or_url: str) -> str:
    value = str(domain_or_url or "").strip().lower()
    if "://" in value:
        value = urlparse(value).hostname or ""
    return value.removeprefix("www.").rstrip(".")


def domain_matches(domain: str, policy_domain: str) -> bool:
    normalized = normalize_domain(domain)
    allowed = normalize_domain(policy_domain)
    return bool(normalized and allowed and (normalized == allowed or normalized.endswith(f".{allowed}")))


def _fallback_tier(name: str, trust_score: float, verdict_strength: str) -> SourceTier:
    return SourceTier(name=name, trust_score=trust_score, verdict_strength=verdict_strength, domains=())


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
