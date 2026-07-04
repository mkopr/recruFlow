import asyncio
import json
import logging
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Source
from app.ingestion.normalize import (
    JUSTJOINIT,
    normalize_remote,
    normalize_salary,
    normalize_seniority,
    to_int,
)
from app.ingestion.persist import ingest_offer
from app.ingestion.types import IngestionResult

JUSTJOINIT_OFFERS_URL = "https://justjoin.it/api/candidate-api/offers"

logger = logging.getLogger(__name__)


def _fetch_justjoinit_json(
    url: str = JUSTJOINIT_OFFERS_URL,
    *,
    params: dict[str, Any] | None = None,
    timeout: float = 10.0,
) -> Any | None:
    try:
        response = httpx.get(
            url, params=params, timeout=timeout, headers={"User-Agent": "recruFlow/0.1"}
        )
        response.raise_for_status()
    except httpx.HTTPError:
        logger.error(
            "failed to fetch JustJoin.it offers: url=%r params=%r", url, params, exc_info=True
        )
        return None

    try:
        return response.json()
    except json.JSONDecodeError:
        logger.error(
            "JustJoin.it returned malformed JSON: url=%r body=%r", url, response.text[:500]
        )
        return None


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


async def _persist_offers(
    session: AsyncSession,
    source_id: int,
    offers: list[dict[str, Any]],
    consecutive_already_seen: int,
) -> tuple[int, int]:
    """Persist offers, returning (created_count, updated consecutive-already-seen streak).

    The streak carries in and out across page boundaries so the caller can early-stop
    pagination once it crosses a threshold — see `run_justjoinit_ingestion`. An offer that
    fails validation (`ingest_offer` returns `None`) is neither new nor already-seen, so it
    leaves the streak unchanged rather than resetting or extending it.
    """
    created_count = 0
    for raw in offers:
        mapped = map_justjoinit_offer(source_id, raw)
        result = await ingest_offer(session, mapped, raw_payload=raw)
        if result is None:
            continue
        _, created = result
        if created:
            created_count += 1
            consecutive_already_seen = 0
        else:
            consecutive_already_seen += 1
    return created_count, consecutive_already_seen


async def run_justjoinit_ingestion(
    session: AsyncSession, source: Source, *, force_refresh: bool = False
) -> IngestionResult:
    config = source.config_json or {}
    url = config.get("endpoint_url", JUSTJOINIT_OFFERS_URL)
    page_size = int(config.get("page_size", 100))
    max_pages = int(config.get("max_pages", 100))
    rate_limit_delay = float(config.get("rate_limit_delay_seconds", 1.0))
    already_seen_stop_threshold = int(config.get("already_seen_stop_threshold", 20))

    total_fetched = 0
    total_created = 0
    consecutive_already_seen = 0
    cursor: int | None = 0
    for page_index in range(max_pages):
        if cursor is None:
            break
        page = _fetch_page(url, cursor=cursor, page_size=page_size)
        if page is None:
            if page_index == 0:
                return IngestionResult(
                    ok=False,
                    fetched=0,
                    created=0,
                    error_message="failed to fetch JustJoin.it offers",
                )
            logger.warning("JustJoin.it pagination stopped early after %d page(s)", page_index)
            break
        offers, cursor = page
        total_fetched += len(offers)
        created_count, consecutive_already_seen = await _persist_offers(
            session, source.id, offers, consecutive_already_seen
        )
        total_created += created_count
        # force_refresh bypasses the BUG02/ADR0009 incremental checkpoint: a caller explicitly
        # asking for a fresh fetch wants the full catalog re-walked, not an early exit the moment
        # it looks like we've caught up.
        if not force_refresh and consecutive_already_seen >= already_seen_stop_threshold:
            logger.info(
                "JustJoin.it pagination stopped early: caught up to %d already-seen offers",
                consecutive_already_seen,
            )
            break
        if cursor is not None and page_index + 1 < max_pages:
            await asyncio.sleep(rate_limit_delay)

    return IngestionResult(ok=True, fetched=total_fetched, created=total_created)
