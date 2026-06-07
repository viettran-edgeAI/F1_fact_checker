from __future__ import annotations

from pydantic import BaseModel, Field


class OCRLineResponse(BaseModel):
    order: int
    text: str
    normalized_text: str = ""
    confidence: float | None = None
    bbox: list[int] | None = None


class OCRTextResponse(BaseModel):
    job_id: str
    text: str
    normalized_text: str
    lines: list[OCRLineResponse] = Field(default_factory=list)
    line_count: int
    meta: dict[str, object] = Field(default_factory=dict)
