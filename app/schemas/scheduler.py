from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ManualRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    connector: str
    trigger_type: str
    status: str
    fetched: int | None
    created: int | None
    warning: bool
    error_message: str | None
    started_at: datetime
    finished_at: datetime | None


class SourceStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_id: int
    connector: str
    name: str
    schedule: dict[str, Any]
    last_fetched_at: datetime | None
    last_run_id: int | None
    last_run_started_at: datetime | None
    last_run_finished_at: datetime | None
    last_run_status: str | None
    last_run_trigger_type: str | None
    last_run_fetched: int | None
    last_run_created: int | None
    last_run_warning: bool
    last_run_error_message: str | None


class SchedulerStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sources: list[SourceStatus]


class IntervalUpdateRequest(BaseModel):
    seconds: int = Field(ge=60)
