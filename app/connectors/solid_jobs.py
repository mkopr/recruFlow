import logging
from typing import Any

from app.connectors.base import JobBoardConnector
from app.ingestion.normalize import (
    SOLID_JOBS,
    normalize_remote,
    normalize_salary,
    normalize_seniority,
)

SOLID_JOBS_OFFERS_URL_TEMPLATE = "https://solid.jobs/public-api/offers/{division}"

logger = logging.getLogger(__name__)


def build_offer_url(config: dict[str, Any]) -> str:
    return SOLID_JOBS_OFFERS_URL_TEMPLATE.format(division=str(config.get("division", "IT")))


def build_offer_params(
    config: dict[str, Any], *, campaign: str, page_index: int, page_size: int
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "campaign": campaign,
        "pageIndex": page_index,
        "pageSize": page_size,
        "sortActive": "validFrom",
        "sortDirection": "desc",
    }

    cities = config.get("cities")
    if cities:
        params["search.cities"] = ",".join(str(city) for city in cities)

    experience_levels = config.get("experience_levels")
    if experience_levels:
        params["search.experiences"] = ",".join(str(level) for level in experience_levels)

    terms = config.get("terms")
    if terms:
        params["search.searchTerm"] = ",".join(str(term) for term in terms)

    min_salary = config.get("min_salary")
    if min_salary is not None:
        params["search.minimumSalary"] = min_salary

    return params


class SolidJobsConnector(JobBoardConnector):
    name = "SOLID.Jobs"
    # Confirmed live 2026-07-05 (see ADR 0012): the direct API wraps offers under "jobs",
    # the same envelope key sjctl's own "search" subcommand used -- not "results"/"data".
    envelope_key = "jobs"

    def __init__(self, *, campaign: str) -> None:
        self.campaign = campaign

    def default_url(self) -> str:
        return build_offer_url({})

    def build_url(self, config: dict[str, Any]) -> str:
        return build_offer_url(config)

    def build_headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"X-Api-Version": "1.0"}

    def build_params(
        self, config: dict[str, Any], *, cursor: Any, page_size: int
    ) -> dict[str, Any]:
        return build_offer_params(
            config, campaign=self.campaign, page_index=cursor, page_size=page_size
        )

    def next_cursor(
        self, payload: Any, offers: list[dict[str, Any]], *, cursor: Any, page_size: int
    ) -> Any | None:
        return cursor + 1 if len(offers) >= page_size else None

    def map_offer(self, source_id: int, raw: dict[str, Any]) -> dict[str, Any]:
        raw_salary = raw.get("salary")
        salary: dict[str, Any] = raw_salary if isinstance(raw_salary, dict) else {}

        raw_locations = raw.get("locations")
        location = (
            ", ".join(str(loc) for loc in raw_locations)
            if isinstance(raw_locations, list) and raw_locations
            else None
        )

        salary_min, salary_max, salary_currency = normalize_salary(
            SOLID_JOBS, salary.get("from"), salary.get("to"), salary.get("currency")
        )

        return {
            "source_id": source_id,
            "external_id": raw.get("jobOfferKey"),
            "canonical_url": raw.get("url"),
            "title": raw.get("title") or "",
            "company": raw.get("company") or "",
            "location": location,
            "remote": normalize_remote(SOLID_JOBS, raw.get("isRemote", False)),
            "seniority": normalize_seniority(SOLID_JOBS, raw.get("experienceLevel")),
            "salary_min": salary_min,
            "salary_max": salary_max,
            "salary_currency": salary_currency,
            "contract_type": salary.get("employmentType"),
            "posted_at": raw.get("validFrom"),
            "description": raw.get("description"),
        }
