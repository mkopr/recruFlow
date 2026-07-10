import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.http import fetch_json
from app.db.models import Source
from app.ingestion.normalize import (
    SOLID_JOBS,
    extract_envelope_list,
    normalize_remote,
    normalize_salary,
    normalize_seniority,
)
from app.ingestion.runner import resolve_fetch_range, run_paginated_ingestion
from app.ingestion.types import IngestionResult

SOLID_JOBS_OFFERS_URL_TEMPLATE = "https://solid.jobs/public-api/offers/{division}"

logger = logging.getLogger(__name__)


def _fetch_solid_jobs_json(
    url: str, *, params: dict[str, Any], timeout: float = 10.0
) -> Any | None:
    return fetch_json(
        url,
        source_name="SOLID.Jobs",
        logger=logger,
        params=params,
        headers={"X-Api-Version": "1.0"},
        timeout=timeout,
    )


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


def _extract_offers(payload: Any) -> list[dict[str, Any]] | None:
    # Confirmed live 2026-07-05 (see ADR 0012): the direct API wraps offers under "jobs",
    # the same envelope key sjctl's own "search" subcommand used -- not "results"/"data".
    return extract_envelope_list(payload, "jobs")


def map_solid_jobs_offer(source_id: int, raw: dict[str, Any]) -> dict[str, Any]:
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


async def run_solid_jobs_ingestion(
    session: AsyncSession, source: Source, *, campaign: str, force_refresh: bool = False
) -> IngestionResult:
    config = source.config_json or {}
    url = build_offer_url(config)
    page_size = int(config.get("page_size", 100))
    max_pages = int(config.get("max_pages", 100))
    already_seen_stop_threshold = int(config.get("already_seen_stop_threshold", 20))
    since, until = resolve_fetch_range(config.get("fetch_range"))

    def fetch_page(
        page_index: int, page_size: int
    ) -> tuple[list[dict[str, Any]], int | None] | None:
        params = build_offer_params(
            config, campaign=campaign, page_index=page_index, page_size=page_size
        )
        payload = _fetch_solid_jobs_json(url, params=params)
        if payload is None:
            return None

        offers = _extract_offers(payload)
        if offers is None:
            logger.error(
                "SOLID.Jobs returned unexpected JSON shape: url=%r page_index=%d", url, page_index
            )
            return None

        next_cursor = page_index + 1 if len(offers) >= page_size else None
        return offers, next_cursor

    return await run_paginated_ingestion(
        session,
        source.id,
        source_name="SOLID.Jobs",
        fetch_page=fetch_page,
        map_offer=map_solid_jobs_offer,
        initial_cursor=0,
        page_size=page_size,
        max_pages=max_pages,
        already_seen_stop_threshold=already_seen_stop_threshold,
        force_refresh=force_refresh,
        logger=logger,
        since=since,
        until=until,
    )
