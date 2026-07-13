import logging
from datetime import UTC, datetime
from typing import Any

from app.connectors.base import JobBoardConnector
from app.ingestion.normalize import (
    NOFLUFFJOBS,
    extract_envelope_list,
    normalize_remote,
    normalize_salary,
    normalize_seniority,
    to_int,
)

NOFLUFFJOBS_OFFERS_URL = "https://nofluffjobs.com/api/joboffers/main"

logger = logging.getLogger(__name__)


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


class NoFluffJobsConnector(JobBoardConnector):
    """`force_refresh` is accepted (via the shared `JobBoardConnector.run`) for interface
    parity with the other connectors but has no effect here: unlike JustJoin.it's
    incremental pagination, this connector has no checkpoint to bypass -- every call
    already issues one full live fetch (see ADR 0009).
    """

    name = "NoFluffJobs"
    envelope_key = "postings"

    def default_url(self) -> str:
        return NOFLUFFJOBS_OFFERS_URL

    def build_params(
        self, config: dict[str, Any], *, cursor: Any, page_size: int
    ) -> dict[str, Any]:
        return {"pageSize": page_size, "salaryCurrency": "PLN", "salaryPeriod": "month"}

    def extract_offers(self, payload: Any) -> list[dict[str, Any]] | None:
        return extract_envelope_list(payload, self.envelope_key, allow_bare_list=False)

    def next_cursor(
        self, payload: Any, offers: list[dict[str, Any]], *, cursor: Any, page_size: int
    ) -> Any | None:
        # NoFluffJobs has no pagination loop (ADR 0009 -- the feed isn't offset-stable): a
        # `next_cursor` of `None` after this one call is the shared runner's no-op case.
        return None

    def runner_kwargs(self, config: dict[str, Any]) -> dict[str, Any]:
        return {"max_pages": 1, "already_seen_stop_threshold": 1}

    def map_offer(self, source_id: int, raw: dict[str, Any]) -> dict[str, Any]:
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
