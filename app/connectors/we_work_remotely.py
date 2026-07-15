import logging
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.http import fetch_xml
from app.db.models import Source
from app.ingestion.normalize import WE_WORK_REMOTELY, normalize_salary
from app.ingestion.runner import resolve_fetch_range, run_paginated_ingestion
from app.ingestion.types import IngestionResult

WE_WORK_REMOTELY_RSS_URL = "https://weworkremotely.com/remote-jobs.rss"

_ITEM_FIELDS: tuple[str, ...] = (
    "title",
    "link",
    "guid",
    "pubDate",
    "region",
    "country",
    "state",
    "skills",
    "category",
    "type",
    "description",
)

_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
# Confirmed live 2026-07-15 against the real feed: a salary line is rare (~1/100 postings)
# and, when present, only ever shaped "Up to USD <amount>" (or a bare "$" sign) -- other
# currencies were not observed, so this intentionally does not attempt to match them rather
# than guess at a currency this feed has never been confirmed to use (OD-9).
_SALARY_CEILING_PATTERN = re.compile(r"up to\s+(?:usd|us\$|\$)\s*([\d][\d,]*)", re.IGNORECASE)

logger = logging.getLogger(__name__)


def _item_to_dict(item: ET.Element) -> dict[str, str | None]:
    return {field: (item.findtext(field) or None) for field in _ITEM_FIELDS}


def _extract_rss_items(root: ET.Element, *, url: str) -> list[dict[str, str | None]] | None:
    channel = root.find("channel")
    if channel is None:
        return None
    return [_item_to_dict(item) for item in channel.findall("item")]


def _split_company_and_title(raw_title: str | None) -> tuple[str | None, str]:
    """We Work Remotely formats every RSS `<title>` as "Company Name: Job Title" (confirmed
    live 2026-07-15, 100/100 sampled items) -- unlike the Domain Decision's original
    assumption, `<description>` carries no company-identifying line at all (its only
    consistently structured fields are a "Headquarters:" *location* line and, rarely, a
    salary line -- see `_parse_salary_ceiling`). Company is therefore split off the title
    here rather than parsed from the description.
    """
    if not raw_title:
        return None, ""
    company, sep, job_title = raw_title.partition(": ")
    if not sep:
        return None, raw_title
    return (company or None), job_title


def _strip_html_tags(text: str) -> str:
    return _HTML_TAG_PATTERN.sub(" ", text)


def _parse_salary_ceiling(description: str | None) -> int | None:
    if not description:
        logger.debug("we work remotely: empty description, no salary to parse")
        return None

    plain = _strip_html_tags(description)
    match = _SALARY_CEILING_PATTERN.search(plain)
    if match is None:
        logger.debug("we work remotely: no salary ceiling line found in description")
        return None

    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        logger.debug("we work remotely: unparseable salary amount: %r", match.group(1))
        return None


def _join_location(raw: dict[str, Any]) -> str | None:
    parts = [raw.get("region"), raw.get("country"), raw.get("state")]
    joined: list[str] = []
    for part in parts:
        if part and part not in joined:
            joined.append(str(part))
    return ", ".join(joined) if joined else None


def _parse_posted_at(raw_pub_date: Any) -> str | None:
    if not isinstance(raw_pub_date, str) or not raw_pub_date:
        return None
    try:
        parsed = parsedate_to_datetime(raw_pub_date)
    except (ValueError, TypeError):
        return None
    return parsed.isoformat()


def map_offer(source_id: int, raw: dict[str, Any]) -> dict[str, Any]:
    company, job_title = _split_company_and_title(raw.get("title"))
    salary_min, salary_max, salary_currency = normalize_salary(
        WE_WORK_REMOTELY, None, _parse_salary_ceiling(raw.get("description")), "USD"
    )

    raw_category = raw.get("category")
    raw_skills = raw.get("skills") or ""
    skills = [skill.strip() for skill in raw_skills.split(",") if skill.strip()]
    category_prefix = [str(raw_category)] if raw_category else []
    industry_tags = list(dict.fromkeys(category_prefix + skills))

    return {
        "source_id": source_id,
        "external_id": raw.get("guid") or None,
        # Confirmed live 2026-07-15: `link` and `guid` are byte-identical for every sampled
        # item, across two polls a few minutes apart -- see ARCHITECTURE.md for the full
        # canonical-URL stability writeup. `link` is used per the Domain Decision's baseline.
        "canonical_url": raw.get("link"),
        "title": job_title or "",
        "company": company or "",
        "location": _join_location(raw),
        "remote": True,
        "seniority": None,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_currency": salary_currency,
        "contract_type": None,
        "posted_at": _parse_posted_at(raw.get("pubDate")),
        "description": raw.get("description"),
        "industry_tags": industry_tags,
    }


def fetch_page(cursor: Any, page_size: int) -> tuple[list[dict[str, Any]], Any | None] | None:
    root = fetch_xml(WE_WORK_REMOTELY_RSS_URL, source_name="We Work Remotely", logger=logger)
    if root is None:
        return None

    items = _extract_rss_items(root, url=WE_WORK_REMOTELY_RSS_URL)
    if items is None:
        logger.error(
            "We Work Remotely returned unexpected feed shape: url=%r", WE_WORK_REMOTELY_RSS_URL
        )
        return None

    return items, None


async def run_we_work_remotely_ingestion(
    session: AsyncSession, source: Source, force_refresh: bool = False
) -> IngestionResult:
    """Implements the `Connector` Protocol (`app/ingestion/registry.py`) directly rather than
    subclassing `JobBoardConnector` -- We Work Remotely's only confirmed public source is an
    RSS/XML feed (its `/api/v1/remote-jobs/` endpoint returns 401, `WWW-Authenticate: Token
    realm="Application"`, confirmed live 2026-07-15; see ARCHITECTURE.md), not JSON, and has
    no cursor, while `JobBoardConnector.fetch_page` is fixed around `fetch_json` plus a
    cursor. This is this connector batch's one deliberate exception (P3US44), not an
    oversight left over from the P3US37 refactor.
    """
    config = source.config_json or {}
    since, until = resolve_fetch_range(config.get("fetch_range"))
    return await run_paginated_ingestion(
        session,
        source.id,
        source_name="We Work Remotely",
        fetch_page=fetch_page,
        map_offer=map_offer,
        initial_cursor=0,
        page_size=1,
        max_pages=1,
        already_seen_stop_threshold=int(config.get("already_seen_stop_threshold", 20)),
        force_refresh=force_refresh,
        logger=logger,
        since=since,
        until=until,
    )
