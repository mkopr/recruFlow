from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    fetch_range: dict[str, Any]
    fetch_scope: dict[str, Any]
    auto_fetch_enabled: bool
    connector_enabled: bool
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


class FetchRangeUpdateRequest(BaseModel):
    mode: Literal["range", "all"]
    since: datetime | None = None
    until: datetime | None = None

    @model_validator(mode="after")
    def _validate_range(self) -> "FetchRangeUpdateRequest":
        if self.mode == "all":
            self.since = None
            self.until = None
            return self

        if self.since is None:
            raise ValueError("since is required when mode is 'range'")
        if self.until is not None and self.since > self.until:
            raise ValueError("since must not be after until")
        return self


class FetchScopeUpdateRequest(BaseModel):
    mode: Literal["all", "filtered"]


class AutoFetchUpdateRequest(BaseModel):
    enabled: bool


class ConnectorEnabledUpdateRequest(BaseModel):
    enabled: bool
