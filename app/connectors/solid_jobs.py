import json
import logging
import subprocess
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Source
from app.ingestion.normalize import (
    SOLID_JOBS,
    normalize_remote,
    normalize_salary,
    normalize_seniority,
)
from app.ingestion.persist import ingest_offer

SJCTL_BINARY = "sjctl"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestionResult:
    ok: bool
    fetched: int
    created: int


def build_search_args(config: dict[str, Any], *, campaign: str) -> list[str]:
    args: list[str] = ["search", "-d", str(config.get("division", "IT"))]
    for city in config.get("cities", []):
        args += ["--city", str(city)]
    min_salary = config.get("min_salary")
    if min_salary is not None:
        args += ["--min-salary", str(min_salary)]
    for level in config.get("experience_levels", []):
        args += ["--experience", str(level)]
    for term in config.get("terms", []):
        args += ["--term", str(term)]
    args += ["--campaign", campaign, "--json"]
    return args


def build_sync_args(*, campaign: str) -> list[str]:
    return ["sync", "--campaign", campaign, "--json"]


def _run_sjctl(args: list[str], *, timeout: float = 30.0) -> Any | None:
    try:
        result = subprocess.run(
            [SJCTL_BINARY, *args], capture_output=True, text=True, timeout=timeout
        )
    except OSError:
        logger.error("failed to invoke sjctl binary: args=%r", args, exc_info=True)
        return None
    except subprocess.TimeoutExpired:
        logger.error("sjctl invocation timed out: args=%r timeout=%s", args, timeout)
        return None

    if result.returncode != 0:
        logger.error(
            "sjctl exited non-zero: args=%r returncode=%d stderr=%s",
            args,
            result.returncode,
            result.stderr.strip(),
        )
        return None

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.error(
            "sjctl returned malformed JSON: args=%r stdout=%r",
            args,
            result.stdout[:500],
        )
        return None


def _extract_offers(
    payload: Any, list_key: str, *, item_key: str | None = None
) -> list[dict[str, Any]] | None:
    if isinstance(payload, list):
        items: list[Any] = payload
    elif isinstance(payload, dict):
        if list_key not in payload:
            return None
        raw_items = payload[list_key]
        if raw_items is None:
            items = []
        elif isinstance(raw_items, list):
            items = raw_items
        else:
            return None
    else:
        return None

    offers = [item for item in items if isinstance(item, dict)]
    if item_key is None:
        return offers
    return [item[item_key] for item in offers if isinstance(item.get(item_key), dict)]


def map_sjctl_offer(source_id: int, raw: dict[str, Any]) -> dict[str, Any]:
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
    if force_refresh:
        args = build_search_args(source.config_json, campaign=campaign)
        list_key, item_key = "jobs", None
    else:
        args = build_sync_args(campaign=campaign)
        list_key, item_key = "new", "offer"

    payload = _run_sjctl(args)
    if payload is None:
        logger.warning("SOLID.Jobs ingestion aborted: sjctl call failed, see prior error")
        return IngestionResult(ok=False, fetched=0, created=0)

    offers = _extract_offers(payload, list_key, item_key=item_key)
    if offers is None:
        logger.error("sjctl returned unexpected JSON shape: args=%r", args)
        return IngestionResult(ok=False, fetched=0, created=0)

    created_count = 0
    for raw in offers:
        mapped = map_sjctl_offer(source.id, raw)
        result = await ingest_offer(session, mapped, raw_payload=raw)
        if result is not None and result[1] is True:
            created_count += 1

    return IngestionResult(ok=True, fetched=len(offers), created=created_count)
