from __future__ import annotations

from pydantic import BaseModel, Field


class FactSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=8, ge=1, le=50)


class FactSearchResponse(BaseModel):
    query: str
    facts: list[dict[str, object]]
