import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.http import fetch_json
from app.db.models import Source
from app.ingestion.normalize import (
    SOLID_JOBS,
    normalize_remote,
    normalize_salary,
    normalize_seniority,
)
from app.ingestion.persist import ingest_offer
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
    if isinstance(payload, list):
        items: list[Any] = payload
    elif isinstance(payload, dict):
        if "jobs" not in payload:
            return None
        raw_items = payload["jobs"]
        if raw_items is None:
            items = []
        elif isinstance(raw_items, list):
            items = raw_items
        else:
            return None
    else:
        return None

    return [item for item in items if isinstance(item, dict)]


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


async def _persist_offers(
    session: AsyncSession,
    source_id: int,
    offers: list[dict[str, Any]],
    consecutive_already_seen: int,
) -> tuple[int, int]:
    """Persist offers, returning (created_count, updated consecutive-already-seen streak).

    The streak carries in and out across page boundaries so the caller can early-stop
    pagination once it crosses a threshold — see `run_solid_jobs_ingestion`. An offer that
    fails validation (`ingest_offer` returns `None`) is neither new nor already-seen, so it
    leaves the streak unchanged rather than resetting or extending it.
    """
    created_count = 0
    for raw in offers:
        mapped = map_solid_jobs_offer(source_id, raw)
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


async def run_solid_jobs_ingestion(
    session: AsyncSession, source: Source, *, campaign: str, force_refresh: bool = False
) -> IngestionResult:
    config = source.config_json or {}
    url = build_offer_url(config)
    page_size = int(config.get("page_size", 100))
    max_pages = int(config.get("max_pages", 100))
    already_seen_stop_threshold = int(config.get("already_seen_stop_threshold", 20))

    total_fetched = 0
    total_created = 0
    consecutive_already_seen = 0
    for page_index in range(max_pages):
        params = build_offer_params(
            config, campaign=campaign, page_index=page_index, page_size=page_size
        )
        payload = _fetch_solid_jobs_json(url, params=params)
        if payload is None:
            if page_index == 0:
                return IngestionResult(
                    ok=False,
                    fetched=0,
                    created=0,
                    error_message="failed to fetch SOLID.Jobs offers",
                )
            logger.warning("SOLID.Jobs pagination stopped early after %d page(s)", page_index)
            break

        offers = _extract_offers(payload)
        if offers is None:
            logger.error(
                "SOLID.Jobs returned unexpected JSON shape: url=%r page_index=%d", url, page_index
            )
            if page_index == 0:
                return IngestionResult(
                    ok=False,
                    fetched=0,
                    created=0,
                    error_message="SOLID.Jobs returned unexpected JSON shape",
                )
            logger.warning("SOLID.Jobs pagination stopped early after %d page(s)", page_index)
            break

        total_fetched += len(offers)
        created_count, consecutive_already_seen = await _persist_offers(
            session, source.id, offers, consecutive_already_seen
        )
        total_created += created_count

        if len(offers) < page_size:
            break

        # force_refresh bypasses the BUG02/ADR0009 incremental checkpoint: a caller explicitly
        # asking for a fresh fetch wants the full catalog re-walked, not an early exit the moment
        # it looks like we've caught up.
        if not force_refresh and consecutive_already_seen >= already_seen_stop_threshold:
            logger.info(
                "SOLID.Jobs pagination stopped early: caught up to %d already-seen offers",
                consecutive_already_seen,
            )
            break

    return IngestionResult(ok=True, fetched=total_fetched, created=total_created)
