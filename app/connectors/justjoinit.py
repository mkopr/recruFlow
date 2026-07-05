import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.http import fetch_json
from app.db.models import Source
from app.ingestion.normalize import (
    JUSTJOINIT,
    normalize_remote,
    normalize_salary,
    normalize_seniority,
    to_int,
)
from app.ingestion.runner import run_paginated_ingestion
from app.ingestion.types import IngestionResult

JUSTJOINIT_OFFERS_URL = "https://justjoin.it/api/candidate-api/offers"

logger = logging.getLogger(__name__)


def _fetch_justjoinit_json(
    url: str = JUSTJOINIT_OFFERS_URL,
    *,
    params: dict[str, Any] | None = None,
    timeout: float = 10.0,
) -> Any | None:
    return fetch_json(url, source_name="JustJoin.it", logger=logger, params=params, timeout=timeout)


def _extract_offer_list(payload: Any) -> list[dict[str, Any]] | None:
    if isinstance(payload, list):
        items: list[Any] = payload
    elif isinstance(payload, dict):
        if "data" not in payload:
            return None
        raw_items = payload["data"]
        if raw_items is None:
            items = []
        elif isinstance(raw_items, list):
            items = raw_items
        else:
            return None
    else:
        return None

    return [item for item in items if isinstance(item, dict)]


def _next_cursor(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        return None
    next_block = meta.get("next")
    if not isinstance(next_block, dict):
        return None
    cursor = next_block.get("cursor")
    return cursor if isinstance(cursor, int) else None


def _fetch_page(
    url: str, *, cursor: int, page_size: int
) -> tuple[list[dict[str, Any]], int | None] | None:
    payload = _fetch_justjoinit_json(url, params={"from": cursor, "itemsCount": page_size})
    if payload is None:
        return None

    offers = _extract_offer_list(payload)
    if offers is None:
        logger.error("JustJoin.it returned unexpected JSON shape: url=%r from=%d", url, cursor)
        return None

    return offers, _next_cursor(payload)


def _first_employment_type(raw: dict[str, Any]) -> dict[str, Any]:
    employment_types = raw.get("employmentTypes")
    if isinstance(employment_types, list) and employment_types:
        first = employment_types[0]
        if isinstance(first, dict):
            return first
    return {}


def map_justjoinit_offer(source_id: int, raw: dict[str, Any]) -> dict[str, Any]:
    raw_locations = raw.get("locations")
    location = (
        ", ".join(
            str(loc["city"]) for loc in raw_locations if isinstance(loc, dict) and loc.get("city")
        )
        if isinstance(raw_locations, list) and raw_locations
        else (raw.get("city") or None)
    )

    primary = _first_employment_type(raw)
    slug = raw.get("slug")

    raw_gross = primary.get("gross") if isinstance(primary.get("gross"), bool) else None
    salary_min, salary_max, salary_currency = normalize_salary(
        JUSTJOINIT,
        to_int(primary.get("from")),
        to_int(primary.get("to")),
        primary.get("currency"),
        raw_gross=raw_gross,
    )

    return {
        "source_id": source_id,
        "external_id": raw.get("guid"),
        "canonical_url": f"https://justjoin.it/job-offer/{slug}" if slug else None,
        "title": raw.get("title") or "",
        "company": raw.get("companyName") or "",
        "location": location or None,
        "remote": normalize_remote(JUSTJOINIT, raw.get("workplaceType")),
        "seniority": normalize_seniority(JUSTJOINIT, raw.get("experienceLevel")),
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_currency": salary_currency,
        "contract_type": primary.get("type"),
        "posted_at": raw.get("publishedAt"),
        "description": None,
    }


async def run_justjoinit_ingestion(
    session: AsyncSession, source: Source, *, force_refresh: bool = False
) -> IngestionResult:
    config = source.config_json or {}
    url = config.get("endpoint_url", JUSTJOINIT_OFFERS_URL)
    page_size = int(config.get("page_size", 100))
    max_pages = int(config.get("max_pages", 100))
    rate_limit_delay = float(config.get("rate_limit_delay_seconds", 1.0))
    already_seen_stop_threshold = int(config.get("already_seen_stop_threshold", 20))

    def fetch_page(cursor: int, page_size: int) -> tuple[list[dict[str, Any]], int | None] | None:
        return _fetch_page(url, cursor=cursor, page_size=page_size)

    return await run_paginated_ingestion(
        session,
        source.id,
        source_name="JustJoin.it",
        fetch_page=fetch_page,
        map_offer=map_justjoinit_offer,
        initial_cursor=0,
        page_size=page_size,
        max_pages=max_pages,
        already_seen_stop_threshold=already_seen_stop_threshold,
        force_refresh=force_refresh,
        logger=logger,
        rate_limit_delay=rate_limit_delay,
    )
