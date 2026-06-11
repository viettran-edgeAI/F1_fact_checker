from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class VerificationStream(str, Enum):
    STRUCTURED = "structured"
    WEB = "web"
    MIXED = "mixed"
    UNSUPPORTED = "unsupported"


class RetrievalRoute(str, Enum):
    STRUCTURED = "structured"
    WEB = "web"


class VerdictLabel(str, Enum):
    SUPPORTS = "SUPPORTS"
    REFUTES = "REFUTES"
    NOT_ENOUGH_INFO = "NOT_ENOUGH_INFO"


class EvidenceSourceType(str, Enum):
    LOCAL_DB = "local_db"
    WEB = "web"


class F1RelevanceLabel(str, Enum):
    F1_RELATED = "f1_related"
    NOT_F1_RELATED = "not_f1_related"


class CheckInputType(str, Enum):
    TEXT = "text"
    URL = "url"
    IMAGE = "image"


class FactSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=8, ge=1, le=50)


class FactSearchResponse(BaseModel):
    query: str
    facts: list[dict[str, object]]


class TextCheckRequest(BaseModel):
    text: str = Field(min_length=1)
    input_type: CheckInputType = CheckInputType.TEXT
    max_claims: int = Field(default=8, ge=1, le=50)
    top_k: int = Field(default=8, ge=1, le=50)
    verification_streams: list[VerificationStream] = Field(
        default_factory=lambda: [
            VerificationStream.STRUCTURED,
            VerificationStream.WEB,
            VerificationStream.MIXED,
        ]
    )
    include_evidence: bool = True
    meta: dict[str, object] = Field(default_factory=dict)


class URLCheckRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    max_claims: int = Field(default=8, ge=1, le=50)
    top_k: int = Field(default=8, ge=1, le=50)
    verification_streams: list[VerificationStream] = Field(
        default_factory=lambda: [
            VerificationStream.STRUCTURED,
            VerificationStream.WEB,
            VerificationStream.MIXED,
        ]
    )
    include_evidence: bool = True
    meta: dict[str, object] = Field(default_factory=dict)


class F1RelevanceResult(BaseModel):
    label: F1RelevanceLabel
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reason: str = ""


class ExtractedClaim(BaseModel):
    claim_id: str
    text: str = Field(min_length=1)
    normalized_text: str = ""
    source_text: str = ""
    start_char: int | None = Field(default=None, ge=0)
    end_char: int | None = Field(default=None, ge=0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    meta: dict[str, object] = Field(default_factory=dict)


class ClassifiedClaim(ExtractedClaim):
    verification_stream: VerificationStream = VerificationStream.UNSUPPORTED
    required_routes: list[RetrievalRoute] = Field(default_factory=list)
    claim_type: str = ""
    entities: list[str] = Field(default_factory=list)
    structured_query: str | None = None
    web_query_hint: str | None = None
    unsupported_reason: str | None = None


class EvidenceItem(BaseModel):
    evidence_id: str | None = None
    source_type: EvidenceSourceType
    title: str = ""
    snippet: str = ""
    url: str | None = None
    source_id: str | None = None
    table: str | None = None
    record_id: str | None = None
    published_at: str | None = None
    retrieved_at: str | None = None
    score: float | None = None
    supports_verdict: VerdictLabel | None = None
    meta: dict[str, object] = Field(default_factory=dict)


class ClaimVerdict(BaseModel):
    claim: ClassifiedClaim
    verdict: VerdictLabel
    verification_stream: VerificationStream
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    rationale: str = ""
    evidence: list[EvidenceItem] = Field(default_factory=list)
    structured_evidence: list[EvidenceItem] = Field(default_factory=list)
    web_evidence: list[EvidenceItem] = Field(default_factory=list)
    meta: dict[str, object] = Field(default_factory=dict)


class FinalCheckResponse(BaseModel):
    text: str
    verdict: VerdictLabel = VerdictLabel.NOT_ENOUGH_INFO
    claims: list[ClaimVerdict] = Field(default_factory=list)
    summary: str = ""
    unsupported_claims: list[ClassifiedClaim] = Field(default_factory=list)
    meta: dict[str, object] = Field(default_factory=dict)
