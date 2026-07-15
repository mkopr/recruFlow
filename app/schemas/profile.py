from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Skill(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1)
    category: str | None = None
    hard: bool = False


def hard_skill_names(profile: "Profile") -> list[str]:
    return [skill.name for skill in profile.skills if skill.hard]


class PastRole(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1)
    company: str = Field(min_length=1)
    start_date: str | None = None
    end_date: str | None = None
    description: str | None = None


class Project(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1)
    description: str | None = None
    tech_stack: list[str] = Field(default_factory=list)
    client: str | None = None
    team_size: int | None = Field(default=None, ge=0)


class Education(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    institution: str = Field(min_length=1)
    degree: str | None = None
    field_of_study: str | None = None
    start_date: str | None = None
    end_date: str | None = None


class Certification(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1)
    issuer: str | None = None
    year: int | None = None


class Language(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1)


class CVExtraction(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    skills: list[Skill] = Field(default_factory=list)
    past_roles: list[PastRole] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    languages: list[Language] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    industry_tags: list[str] = Field(default_factory=list)
    headline: str | None = None
    summary: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    links: list[str] = Field(default_factory=list)


class Profile(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    skills: list[Skill] = Field(default_factory=list)
    past_roles: list[PastRole] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    languages: list[Language] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    industry_tags: list[str] = Field(default_factory=list)
    headline: str | None = None
    summary: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    links: list[str] = Field(default_factory=list)
    contract_type_preference: str | None = None
    salary_min: int | None = Field(default=None, ge=0)
    salary_target: int | None = Field(default=None, ge=0)
    location_preference: str | None = None
    remote_preference: bool | None = None
    deal_breakers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_salary_target_not_below_min(self) -> "Profile":
        if (
            self.salary_min is not None
            and self.salary_target is not None
            and self.salary_target < self.salary_min
        ):
            raise ValueError("salary_target must not be less than salary_min")
        return self


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    status: str
    is_active: bool
    profile: Profile
    created_at: datetime
    updated_at: datetime
