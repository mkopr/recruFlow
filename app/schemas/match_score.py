from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MatchEngine = Literal["langchain", "sjctl"]


class MatchScore(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    offer_id: int = Field(gt=0)
    profile_id: int = Field(gt=0)
    engine: MatchEngine
    score_percent: int = Field(ge=0, le=100)
    dimensions: dict[str, float] = Field(default_factory=dict)
    rationale: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MatchScoreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    offer_id: int
    profile_id: int
    engine: str
    score_percent: int
    dimensions: dict[str, float]
    rationale: str | None
    created_at: datetime
