import logging
from datetime import UTC, datetime
from typing import Any

from app.connectors.base import JobBoardConnector
from app.connectors.http import fetch_json
from app.ingestion.normalize import REMOTIVE, extract_envelope_list, normalize_salary

REMOTIVE_URL = "https://remotive.com/api/remote-jobs"
DEFAULT_CATEGORIES: tuple[str, ...] = ("software-development", "devops", "qa", "data")

# Maps the slugs `categories` config selects on to the exact display-name string Remotive
# stamps on each job's own `category` field (confirmed live via
# https://remotive.com/api/remote-jobs/categories, 2026-07-15) -- used for *client-side*
# filtering post-fetch, since the API's `category` query param turned out to be a no-op (see
# `fetch_page`).
CATEGORY_SLUG_TO_NAME: dict[str, str] = {
    "software-development": "Software Development",
    "devops": "Devops",
    "qa": "Quality Assurance",
    "data": "Data and Analytics",
}

logger = logging.getLogger(__name__)


def _normalize_posted_at(value: Any) -> str | None:
    # Remotive's `publication_date` is UTC but carries no timezone suffix (e.g.
    # "2026-07-13T07:05:10", confirmed live 2026-07-14) -- `run_paginated_ingestion`'s
    # fetch-range filter compares `posted_at` against an offset-aware `since`/`until` bound
    # and raises `TypeError: can't compare offset-naive and offset-aware datetimes` on a
    # naive value, so this must attach UTC before returning rather than passing the raw
    # string through untouched.
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.isoformat()


class RemotiveConnector(JobBoardConnector):
    """Remotive's public `/api/remote-jobs` endpoint documents a `category` query param, but
    it's a no-op on the free tier this connector uses: every category value returns the
    identical ~38-job snapshot, confirmed live 2026-07-15 -- including jobs from categories
    never in `DEFAULT_CATEGORIES` (Sales, Marketing, Medical, ...), which had been silently
    reaching the DB since this connector's initial implementation despite the config's
    documented intent to scope to IT-relevant categories only. Querying per-category anyway
    (as this connector used to) means N identical requests every run for nothing -- against
    Remotive's own stated terms ("max. 4 times a day ... excessive requests will be blocked"),
    that's a real risk of losing API access entirely. `fetch_page` now fetches once and
    filters by category client-side instead, which both fixes the request volume and makes
    the category scope actually work for the first time.
    """

    name = "Remotive"
    envelope_key = "jobs"

    def default_url(self) -> str:
        return REMOTIVE_URL

    def build_params(
        self, config: dict[str, Any], *, cursor: Any, page_size: int
    ) -> dict[str, Any]:
        # Unused: this connector overrides `fetch_page` directly (see class docstring), but
        # must still provide a concrete implementation to satisfy JobBoardConnector's
        # abstractmethod.
        return {}

    def next_cursor(
        self, payload: Any, offers: list[dict[str, Any]], *, cursor: Any, page_size: int
    ) -> Any | None:
        # Unused stub for the same reason as `build_params` above -- also documents that this
        # is a single-shot, merge-all-categories feed, not real pagination.
        return None

    def map_offer(self, source_id: int, raw: dict[str, Any]) -> dict[str, Any]:
        raw_id = raw.get("id")
        salary_min, salary_max, salary_currency = normalize_salary(REMOTIVE, None, None, "USD")

        raw_category = raw.get("category")
        raw_tags = raw.get("tags")
        tags = (
            [str(tag) for tag in raw_tags if isinstance(tag, str)]
            if isinstance(raw_tags, list)
            else []
        )
        category_prefix = [str(raw_category)] if raw_category else []
        industry_tags = list(dict.fromkeys(category_prefix + tags))

        return {
            "source_id": source_id,
            "external_id": str(raw_id) if raw_id is not None else None,
            "canonical_url": raw.get("url"),
            "title": raw.get("title") or "",
            "company": raw.get("company_name") or "",
            "location": raw.get("candidate_required_location") or None,
            "remote": True,
            "seniority": None,
            "salary_min": salary_min,
            "salary_max": salary_max,
            "salary_currency": salary_currency,
            "contract_type": None,
            "posted_at": _normalize_posted_at(raw.get("publication_date")),
            "description": raw.get("description"),
            "industry_tags": industry_tags,
        }

    def fetch_page(
        self, config: dict[str, Any], cursor: Any, page_size: int
    ) -> tuple[list[dict[str, Any]], Any | None] | None:
        categories = [str(c) for c in config.get("categories") or DEFAULT_CATEGORIES]

        allowed_names: set[str] = set()
        for slug in categories:
            name = CATEGORY_SLUG_TO_NAME.get(slug)
            if name is None:
                logger.warning("%s: unrecognized category slug %r, skipping", self.name, slug)
                continue
            allowed_names.add(name)

        url = self.default_url()
        payload = fetch_json(url, source_name=self.name, logger=logger, params={})
        if payload is None:
            return None

        offers = extract_envelope_list(payload, self.envelope_key)
        if offers is None:
            logger.error("%s returned unexpected JSON shape: url=%r", self.name, url)
            return None

        filtered_offers = [offer for offer in offers if offer.get("category") in allowed_names]
        return filtered_offers, None
