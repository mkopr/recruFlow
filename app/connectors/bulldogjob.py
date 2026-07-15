import json
import logging
import re
from typing import Any
from urllib.parse import quote

from app.connectors.http import fetch_gzip_xml
from app.connectors.sitemap import parse_sitemap_locs
from app.connectors.sitemap_detail import SitemapDetailPageConnector
from app.ingestion.normalize import (
    BULLDOGJOB,
    normalize_remote,
    normalize_salary,
    normalize_seniority,
    to_int,
)

BULLDOGJOB_SITEMAP_INDEX_URL = "https://bulldogjob.com/sitemap.en.xml.gz"
# Confirmed live 2026-07-15 (see `docs/adr/0027`): a real Next.js page, server-side
# skill-matching (case-insensitive), but pagination is client-side only -- a plain-request
# fetch always gets exactly this page's up-to-50 job summaries, regardless of `totalCount`.
BULLDOGJOB_FILTERED_LISTING_URL_TEMPLATE = "https://bulldogjob.com/companies/jobs/s/skills,{term}"

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


class BulldogjobConnector(SitemapDetailPageConnector):
    """Bulldogjob has no offset/cursor-paginated endpoint (US38's Domain Decision): its real
    "next page" affordance is a client-side call not observable from a plain request (see
    `docs/adr/0023-bulldogjob-sitemap-and-embedded-next-data-investigation.md`). This connector
    instead enumerates every live job URL from Bulldogjob's own sitemap, then live-fetches each
    URL's HTML and parses its embedded `__NEXT_DATA__` JSON, via the shared
    `SitemapDetailPageConnector` base (US46, see also `RocketJobsConnector`).
    """

    name = "Bulldogjob"

    def supports_fetch_scope(self) -> bool:
        return True

    def sitemap_url(self) -> str:
        return BULLDOGJOB_SITEMAP_INDEX_URL

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

        sub_sitemap_urls = parse_sitemap_locs(index_xml, "sitemap")
        if not sub_sitemap_urls:
            logger.error("Bulldogjob sitemap index had no sub-sitemaps: url=%r", index_url)
            return None

        jobs_sitemap_url = next(
            (url for url in sub_sitemap_urls if "jobs" in url), sub_sitemap_urls[0]
        )

        jobs_xml = fetch_gzip_xml(jobs_sitemap_url, source_name=self.name, logger=logger)
        if jobs_xml is None:
            return None

        urls = parse_sitemap_locs(jobs_xml, "url")
        return [url for url in urls if _JOB_URL_PATTERN.match(url)]

    def extract_detail_json(self, html: str, *, url: str | None) -> dict[str, Any] | None:
        return extract_next_data(html, url=url)

    def fetch_filtered_sitemap_urls(self, config: dict[str, Any], term: str) -> list[str] | None:
        listing_url = BULLDOGJOB_FILTERED_LISTING_URL_TEMPLATE.format(term=quote(term, safe=""))
        html = self._fetch_detail_html(listing_url)
        if html is None:
            return None

        next_data = extract_next_data(html, url=listing_url)
        if next_data is None:
            return None

        page_props = next_data.get("props", {}).get("pageProps", {})
        jobs = page_props.get("jobs") if isinstance(page_props, dict) else None
        if not isinstance(jobs, list):
            logger.error("Bulldogjob filtered listing had unexpected shape: url=%r", listing_url)
            return None

        return [
            f"https://bulldogjob.com/companies/jobs/{job['id']}"
            for job in jobs
            if isinstance(job, dict) and job.get("id")
        ]
