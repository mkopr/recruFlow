from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class IngestionFailureResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    scheduler_run_id: int | None
    page: int | None
    failure_type: str
    error_message: str
    raw_payload: dict[str, Any] | None
    status: str
    occurred_at: datetime
    resolved_at: datetime | None


class ScoringFailureResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    offer_id: int
    profile_id: int
    failure_type: str
    error_message: str
    raw_payload: dict[str, Any] | None
    status: str
    occurred_at: datetime
    resolved_at: datetime | None


class IngestionFailureListResponse(BaseModel):
    items: list[IngestionFailureResponse]
    total: int


class ScoringFailureListResponse(BaseModel):
    items: list[ScoringFailureResponse]
    total: int
