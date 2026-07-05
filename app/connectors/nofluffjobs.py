import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.http import fetch_json
from app.db.models import Source
from app.ingestion.normalize import (
    NOFLUFFJOBS,
    normalize_remote,
    normalize_salary,
    normalize_seniority,
    to_int,
)
from app.ingestion.runner import run_paginated_ingestion
from app.ingestion.types import IngestionResult

NOFLUFFJOBS_OFFERS_URL = "https://nofluffjobs.com/api/joboffers/main"

logger = logging.getLogger(__name__)


def _fetch_nofluffjobs_json(
    url: str = NOFLUFFJOBS_OFFERS_URL,
    *,
    params: dict[str, Any] | None = None,
    timeout: float = 10.0,
) -> Any | None:
    return fetch_json(url, source_name="NoFluffJobs", logger=logger, params=params, timeout=timeout)


def _extract_offer_list(payload: Any) -> list[dict[str, Any]] | None:
    if not isinstance(payload, dict) or "postings" not in payload:
        return None
    postings = payload["postings"]
    if postings is None:
        return []
    if not isinstance(postings, list):
        return None
    return [item for item in postings if isinstance(item, dict)]


def _epoch_ms_to_datetime(value: Any) -> datetime | None:
    if not isinstance(value, int | float):
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC)


def _join_cities(location: dict[str, Any]) -> str | None:
    places = location.get("places")
    if not isinstance(places, list) or not places:
        return None
    cities = [
        str(place["city"]) for place in places if isinstance(place, dict) and place.get("city")
    ]
    return ", ".join(cities) if cities else None


def map_nofluffjobs_offer(source_id: int, raw: dict[str, Any]) -> dict[str, Any]:
    raw_location = raw.get("location")
    location: dict[str, Any] = raw_location if isinstance(raw_location, dict) else {}

    raw_salary = raw.get("salary")
    salary: dict[str, Any] = raw_salary if isinstance(raw_salary, dict) else {}

    url = raw.get("url")

    salary_min, salary_max, salary_currency = normalize_salary(
        NOFLUFFJOBS,
        to_int(salary.get("from")),
        to_int(salary.get("to")),
        salary.get("currency"),
    )

    return {
        "source_id": source_id,
        "external_id": raw.get("id"),
        "canonical_url": f"https://nofluffjobs.com/job/{url}" if url else None,
        "title": raw.get("title") or "",
        "company": raw.get("name") or "",
        "location": _join_cities(location),
        "remote": normalize_remote(NOFLUFFJOBS, location.get("fullyRemote", False)),
        "seniority": normalize_seniority(NOFLUFFJOBS, raw.get("seniority")),
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_currency": salary_currency,
        "contract_type": salary.get("type") or None,
        "posted_at": _epoch_ms_to_datetime(raw.get("posted")),
        "description": None,
    }


async def run_nofluffjobs_ingestion(
    session: AsyncSession, source: Source, *, force_refresh: bool = False
) -> IngestionResult:
    # force_refresh is accepted for interface parity with the other connectors but has no effect
    # here: unlike JustJoin.it's early-stop pagination, this connector has no incremental
    # checkpoint to bypass -- every call already issues one full live fetch (see ADR 0009).
    config = source.config_json or {}
    url = config.get("endpoint_url", NOFLUFFJOBS_OFFERS_URL)
    page_size = int(config.get("page_size", 100))

    def fetch_page(cursor: int, page_size: int) -> tuple[list[dict[str, Any]], int | None] | None:
        payload = _fetch_nofluffjobs_json(
            url, params={"pageSize": page_size, "salaryCurrency": "PLN", "salaryPeriod": "month"}
        )
        if payload is None:
            return None

        offers = _extract_offer_list(payload)
        if offers is None:
            logger.error("NoFluffJobs returned unexpected JSON shape: url=%r", url)
            return None

        # NoFluffJobs has no pagination loop (ADR 0009 -- the feed isn't offset-stable): a
        # `next_cursor` of `None` after this one call is the shared runner's no-op case.
        return offers, None

    return await run_paginated_ingestion(
        session,
        source.id,
        source_name="NoFluffJobs",
        fetch_page=fetch_page,
        map_offer=map_nofluffjobs_offer,
        initial_cursor=0,
        page_size=page_size,
        max_pages=1,
        already_seen_stop_threshold=1,
        force_refresh=force_refresh,
        logger=logger,
    )
