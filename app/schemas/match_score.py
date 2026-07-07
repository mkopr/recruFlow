from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MatchEngine = Literal["langchain", "sjctl"]
MatchGrade = Literal["A", "B", "C", "D", "F"]

# Best-to-worst grade ordering; a "minimum grade" filter keeps grades at or
# before its index here (e.g. min_grade="B" keeps A and B).
GRADE_ORDER: tuple[MatchGrade, ...] = ("A", "B", "C", "D", "F")


class MatchScore(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    offer_id: int = Field(gt=0)
    profile_id: int = Field(gt=0)
    engine: MatchEngine
    grade: MatchGrade
    dimensions: dict[str, float] = Field(default_factory=dict)
    rationale: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MatchScoreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    offer_id: int
    profile_id: int
    engine: str
    grade: str
    dimensions: dict[str, float]
    rationale: str | None
    created_at: datetime
