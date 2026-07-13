import logging
from typing import Any

from app.connectors.base import JobBoardConnector
from app.ingestion.normalize import (
    JUSTJOINIT,
    normalize_remote,
    normalize_salary,
    normalize_seniority,
    to_int,
)

JUSTJOINIT_OFFERS_URL = "https://justjoin.it/api/candidate-api/offers"

logger = logging.getLogger(__name__)


def _first_employment_type(raw: dict[str, Any]) -> dict[str, Any]:
    employment_types = raw.get("employmentTypes")
    if isinstance(employment_types, list) and employment_types:
        first = employment_types[0]
        if isinstance(first, dict):
            return first
    return {}


class JustJoinItConnector(JobBoardConnector):
    name = "JustJoin.it"
    envelope_key = "data"

    def default_url(self) -> str:
        return JUSTJOINIT_OFFERS_URL

    def build_params(
        self, config: dict[str, Any], *, cursor: Any, page_size: int
    ) -> dict[str, Any]:
        return {"from": cursor, "itemsCount": page_size}

    def next_cursor(
        self, payload: Any, offers: list[dict[str, Any]], *, cursor: Any, page_size: int
    ) -> Any | None:
        if not isinstance(payload, dict):
            return None
        meta = payload.get("meta")
        if not isinstance(meta, dict):
            return None
        next_block = meta.get("next")
        if not isinstance(next_block, dict):
            return None
        next_cursor = next_block.get("cursor")
        return next_cursor if isinstance(next_cursor, int) else None

    def runner_kwargs(self, config: dict[str, Any]) -> dict[str, Any]:
        return {"rate_limit_delay": float(config.get("rate_limit_delay_seconds", 1.0))}

    def map_offer(self, source_id: int, raw: dict[str, Any]) -> dict[str, Any]:
        raw_locations = raw.get("locations")
        location = (
            ", ".join(
                str(loc["city"])
                for loc in raw_locations
                if isinstance(loc, dict) and loc.get("city")
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
