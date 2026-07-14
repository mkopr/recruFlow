import json
import logging
import re
import time
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.base import JobBoardConnector
from app.connectors.http import fetch_gzip_xml
from app.connectors.sitemap import _parse_sitemap_locs, next_sitemap_cursor, resolve_sitemap_cursor
from app.db.models import Source
from app.ingestion.normalize import (
    BULLDOGJOB,
    normalize_remote,
    normalize_salary,
    normalize_seniority,
    to_int,
)
from app.ingestion.runner import resolve_fetch_range, run_paginated_ingestion
from app.ingestion.types import IngestionResult

BULLDOGJOB_SITEMAP_INDEX_URL = "https://bulldogjob.com/sitemap.en.xml.gz"

# BUG42-followup: BUG41's cursor-persistence fix let a run actually walk hundreds of detail
# pages in a row for the first time (previously every run restarted at cursor 0 and never got
# far past page 1) -- doing that with zero delay between requests got bulldogjob.com's own
# per-IP rate limiter to return real 429s mid-run, confirmed live 2026-07-14. This default is
# a starting throttle, not tuned against a documented limit.
DEFAULT_RATE_LIMIT_DELAY_SECONDS = 0.5

_NEXT_DATA_PATTERN = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)
# The `jobs.xml.gz` sub-sitemap mixes real job detail URLs (`/companies/jobs/<id>-<slug>`)
# with filter/tag listing pages (`/companies/jobs/s/skills,Java`, `/companies/jobs/s/role,qa`,
# ...) that share the same `<script id="__NEXT_DATA__">` shape but carry no `job` record --
# confirmed live 2026-07-13 (~5% of sitemap entries). Only the former are real offers.
_JOB_URL_PATTERN = re.compile(r"^https://bulldogjob\.com/companies/jobs/\d+-")

logger = logging.getLogger(__name__)


def extract_next_data(html: str, *, url: str | None = None) -> dict[str, Any] | None:
    match = _NEXT_DATA_PATTERN.search(html)
    if match is None:
        logger.error("Bulldogjob returned unexpected page shape: url=%r", url)
        return None

    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError:
        logger.error("Bulldogjob returned unexpected page shape: url=%r", url)
        return None

    return parsed if isinstance(parsed, dict) else None


def _join_locations(job: dict[str, Any]) -> str | None:
    raw_locations = job.get("locations")
    if not isinstance(raw_locations, list):
        return None

    cities: list[str] = []
    for entry in raw_locations:
        if not isinstance(entry, dict):
            continue
        location = entry.get("location")
        if isinstance(location, dict) and location.get("cityEn"):
            cities.append(str(location["cityEn"]))

    return ", ".join(cities) if cities else None


def _pick_salary(job: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    # Bulldogjob exposes up to three parallel salary blocks depending on the contract types
    # offered for the same posting; `employmentSalary` (UoP-shaped) is preferred as the most
    # standard figure, falling back to `b2bSalary` then `otherSalary`.
    for key, contract_type in (
        ("employmentSalary", "employment"),
        ("b2bSalary", "b2b"),
        ("otherSalary", "other"),
    ):
        salary = job.get(key)
        if isinstance(salary, dict):
            return salary, contract_type

    return {}, None


class BulldogjobConnector(JobBoardConnector):
    """Bulldogjob has no offset/cursor-paginated endpoint (US38's Domain Decision): its real
    "next page" affordance is a client-side call not observable from a plain request (see
    `docs/adr/0023-bulldogjob-sitemap-and-embedded-next-data-investigation.md`). This connector
    instead enumerates every live job URL from Bulldogjob's own sitemap, then live-fetches each
    URL's HTML and parses its embedded `__NEXT_DATA__` JSON -- so it overrides both `fetch_page`
    and `run` rather than using the inherited cursor-pagination loop, the same deviation
    `NoFluffJobsConnector` documents for its own single-shot feed.
    """

    name = "Bulldogjob"

    def default_url(self) -> str:
        return BULLDOGJOB_SITEMAP_INDEX_URL

    def build_params(
        self, config: dict[str, Any], *, cursor: Any, page_size: int
    ) -> dict[str, Any]:
        # Bulldogjob's fetch shape has no query-parameterized page call -- see class docstring.
        return {}

    def next_cursor(
        self, payload: Any, offers: list[dict[str, Any]], *, cursor: Any, page_size: int
    ) -> Any | None:
        return None

    def map_offer(self, source_id: int, raw: dict[str, Any]) -> dict[str, Any]:
        raw_data = raw.get("props", {}).get("pageProps", {}).get("data", {})
        data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
        raw_job = data.get("job")
        job: dict[str, Any] = raw_job if isinstance(raw_job, dict) else {}

        job_id = job.get("id")

        raw_company = job.get("company")
        company: dict[str, Any] = raw_company if isinstance(raw_company, dict) else {}

        salary, contract_type = _pick_salary(job)
        salary_min, salary_max, salary_currency = normalize_salary(
            BULLDOGJOB,
            to_int(salary.get("minValue")),
            to_int(salary.get("maxValue")),
            salary.get("currency"),
        )

        description_parts = [part for part in (job.get("offer"), job.get("requirements")) if part]

        return {
            "source_id": source_id,
            "external_id": job_id,
            "canonical_url": (
                f"https://bulldogjob.com/companies/jobs/{job_id}" if job_id else None
            ),
            "title": job.get("position") or "",
            "company": company.get("name") or "",
            "location": _join_locations(job),
            "remote": normalize_remote(BULLDOGJOB, job.get("remote", False)),
            "seniority": normalize_seniority(BULLDOGJOB, job.get("experienceLevel")),
            "salary_min": salary_min,
            "salary_max": salary_max,
            "salary_currency": salary_currency,
            "contract_type": contract_type,
            "posted_at": job.get("publishedAt"),
            "description": "\n\n".join(description_parts) if description_parts else None,
        }

    def fetch_sitemap_urls(self, config: dict[str, Any]) -> list[str] | None:
        index_url = self.build_url(config)
        index_xml = fetch_gzip_xml(index_url, source_name=self.name, logger=logger)
        if index_xml is None:
            return None

        sub_sitemap_urls = _parse_sitemap_locs(index_xml, "sitemap")
        if not sub_sitemap_urls:
            logger.error("Bulldogjob sitemap index had no sub-sitemaps: url=%r", index_url)
            return None

        jobs_sitemap_url = next(
            (url for url in sub_sitemap_urls if "jobs" in url), sub_sitemap_urls[0]
        )

        jobs_xml = fetch_gzip_xml(jobs_sitemap_url, source_name=self.name, logger=logger)
        if jobs_xml is None:
            return None

        urls = _parse_sitemap_locs(jobs_xml, "url")
        return [url for url in urls if _JOB_URL_PATTERN.match(url)]

    def _fetch_detail_html(self, url: str) -> str | None:
        try:
            response = httpx.get(url, timeout=10.0, headers={"User-Agent": "recruFlow/0.1"})
            response.raise_for_status()
        except httpx.HTTPError:
            logger.error("failed to fetch %s detail page: url=%r", self.name, url, exc_info=True)
            return None
        return response.text

    async def run(
        self, session: AsyncSession, source: Source, force_refresh: bool = False
    ) -> IngestionResult:
        config = source.config_json or {}
        since, until = resolve_fetch_range(config.get("fetch_range"))
        # Each Bulldogjob "page" is `page_size` live per-URL HTTP fetches, not one batched API
        # call, so these fallback bounds cap total live traffic per run at `page_size *
        # max_pages` (20 * 50 = 1000), comfortably covering the ~1000-URL sitemap observed live
        # 2026-07-13 -- unlike the other three connectors' cheap single-request pages.
        page_size = int(config.get("page_size", 20))
        max_pages = int(config.get("max_pages", 50))
        already_seen_stop_threshold = int(config.get("already_seen_stop_threshold", 20))
        rate_limit_delay_seconds = float(
            config.get("rate_limit_delay_seconds", DEFAULT_RATE_LIMIT_DELAY_SECONDS)
        )

        urls = self.fetch_sitemap_urls(config)
        if urls is None:
            return IngestionResult(
                ok=False, fetched=0, created=0, error_message=f"failed to fetch {self.name} offers"
            )

        # BUG41: sitemap order is stable but not recency-sorted, so restarting at cursor 0
        # every run just re-walks the same already-ingested prefix forever. `sitemap_cursor`
        # persists where the previous run left off; `last_cursor` tracks this run's true end
        # (including "reached the end", i.e. `None`) so it can be written back below.
        initial_cursor = resolve_sitemap_cursor(config, len(urls))
        last_cursor: int | None = initial_cursor

        def fetch_page(
            cursor: int, page_size: int
        ) -> tuple[list[dict[str, Any]], int | None] | None:
            nonlocal last_cursor
            chunk_urls = urls[cursor : cursor + page_size]
            if not chunk_urls:
                last_cursor = None
                return [], None

            offers: list[dict[str, Any]] = []
            for url in chunk_urls:
                if rate_limit_delay_seconds > 0:
                    time.sleep(rate_limit_delay_seconds)
                html = self._fetch_detail_html(url)
                if html is None:
                    continue
                parsed = extract_next_data(html, url=url)
                if parsed is None:
                    continue
                offers.append(parsed)

            next_cursor = cursor + page_size if cursor + page_size < len(urls) else None
            last_cursor = next_cursor
            return offers, next_cursor

        result = await run_paginated_ingestion(
            session,
            source.id,
            source_name=self.name,
            fetch_page=fetch_page,
            map_offer=self.map_offer,
            initial_cursor=initial_cursor,
            page_size=page_size,
            max_pages=max_pages,
            already_seen_stop_threshold=already_seen_stop_threshold,
            force_refresh=force_refresh,
            logger=logger,
            since=since,
            until=until,
            # Bulldogjob's sitemap isn't sorted newest-first (see the class docstring and
            # ADR 0017) -- a sitemap-order page being wholly older than `since` says nothing
            # about the rest of the catalog, so that early-stop must not apply here (BUG41).
            sorted_by_recency=False,
        )
        source.config_json = {**config, "sitemap_cursor": next_sitemap_cursor(last_cursor)}
        return result
