import logging
from typing import Any

from app.connectors.base import JobBoardConnector
from app.ingestion.normalize import REMOTEOK, extract_envelope_list, normalize_salary, to_int

REMOTEOK_URL = "https://remoteok.com/api"

logger = logging.getLogger(__name__)


def _zero_to_none(value: Any) -> int | None:
    numeric = to_int(value)
    return numeric if numeric else None


class RemoteOKConnector(JobBoardConnector):
    name = "RemoteOK"
    envelope_key = ""

    def default_url(self) -> str:
        return REMOTEOK_URL

    def build_params(
        self, config: dict[str, Any], *, cursor: Any, page_size: int
    ) -> dict[str, Any]:
        return {}

    def extract_offers(self, payload: Any) -> list[dict[str, Any]] | None:
        if not isinstance(payload, list) or not payload:
            return None
        return extract_envelope_list(payload[1:], self.envelope_key)

    def next_cursor(
        self, payload: Any, offers: list[dict[str, Any]], *, cursor: Any, page_size: int
    ) -> Any | None:
        return None

    def map_offer(self, source_id: int, raw: dict[str, Any]) -> dict[str, Any]:
        raw_id = raw.get("id")
        salary_min, salary_max, salary_currency = normalize_salary(
            REMOTEOK,
            _zero_to_none(raw.get("salary_min")),
            _zero_to_none(raw.get("salary_max")),
            "USD",
        )
        raw_tags = raw.get("tags")

        return {
            "source_id": source_id,
            "external_id": str(raw_id) if raw_id is not None else None,
            "canonical_url": raw.get("url") or raw.get("apply_url"),
            "title": raw.get("position") or "",
            "company": raw.get("company") or "",
            "location": raw.get("location") or None,
            "remote": True,
            "seniority": None,
            "salary_min": salary_min,
            "salary_max": salary_max,
            "salary_currency": salary_currency,
            "contract_type": None,
            "posted_at": raw.get("date"),
            "description": raw.get("description"),
            "industry_tags": [str(tag) for tag in raw_tags] if isinstance(raw_tags, list) else [],
        }
