from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Offer(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, from_attributes=True)

    source_id: int = Field(gt=0)
    external_id: str | None = Field(default=None, max_length=255)
    canonical_url: str | None = Field(default=None, max_length=2048)
    title: str = Field(min_length=1, max_length=500)
    company: str = Field(min_length=1, max_length=255)
    location: str | None = None
    remote: bool = False
    seniority: str | None = Field(default=None, max_length=50)
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    salary_currency: str = Field(default="PLN", min_length=3, max_length=3)
    contract_type: str | None = Field(default=None, max_length=50)
    posted_at: datetime | None = None
    description: str | None = None
    industry_tags: list[str] = Field(default_factory=list)

    @field_validator("canonical_url", mode="after")
    @classmethod
    def _empty_canonical_url_to_none(cls, value: str | None) -> str | None:
        return value or None

    @model_validator(mode="after")
    def _check_salary_range(self) -> "Offer":
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_min > self.salary_max
        ):
            raise ValueError("salary_min must not exceed salary_max")
        return self


class OfferSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    external_id: str | None
    canonical_url: str | None
    title: str
    company: str
    location: str | None
    remote: bool
    seniority: str | None
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    contract_type: str | None
    posted_at: datetime | None
    industry_tags: list[str]
    created_at: datetime
    applied: bool
    hide: bool
    notes: str | None
    link_opened_at: datetime | None
    score_percent: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Active profile's most recent match score (0-100) for this offer, if scored",
    )


class OfferDetail(OfferSummary):
    description: str | None
    raw_payload: dict[str, Any]
    updated_at: datetime


class OfferEdit(BaseModel):
    applied: bool | None = None
    hide: bool | None = None
    notes: str | None = None
    link_opened: bool | None = None


class OfferListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[OfferSummary]
    total: int = Field(description="Total offers matching the filters, ignoring limit/offset")


class OfferCleanupPreviewResponse(BaseModel):
    would_delete: int
    would_skip: int


class DeleteOffersResponse(BaseModel):
    deleted: int
    skipped: int
