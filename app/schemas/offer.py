from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Offer(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, from_attributes=True)

    source_id: int = Field(gt=0)
    external_id: str | None = Field(default=None, max_length=255)
    canonical_url: str | None = Field(default=None, max_length=2048)
    title: str = Field(min_length=1, max_length=500)
    company: str = Field(min_length=1, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    remote: bool = False
    seniority: str | None = Field(default=None, max_length=50)
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    salary_currency: str = Field(default="PLN", min_length=3, max_length=3)
    contract_type: str | None = Field(default=None, max_length=50)
    posted_at: datetime | None = None
    description: str | None = None

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
