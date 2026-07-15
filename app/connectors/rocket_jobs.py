import json
import logging
import re
from typing import Any
from urllib.parse import urlparse

from app.connectors.http import fetch_text
from app.connectors.sitemap import parse_sitemap_locs
from app.connectors.sitemap_detail import SitemapDetailPageConnector
from app.ingestion.normalize import (
    ROCKET_JOBS,
    normalize_remote,
    normalize_salary,
    normalize_seniority,
    to_int,
)

ROCKET_JOBS_SITEMAP_URL = "https://rocketjobs.pl/sitemaps/active-jobs.xml"

# JSON-LD script tags can appear multiple times per page (breadcrumbs, org data, ...), unlike
# Bulldogjob's single `__NEXT_DATA__` block, so every match is inspected for `@type` rather
# than assuming the first `<script>` found is the right one.
_JSON_LD_PATTERN = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL
)

logger = logging.getLogger(__name__)


def _find_job_posting(node: Any) -> dict[str, Any] | None:
    if isinstance(node, dict):
        if node.get("@type") == "JobPosting":
            return node
        graph = node.get("@graph")
        if isinstance(graph, list):
            for entry in graph:
                found = _find_job_posting(entry)
                if found is not None:
                    return found
    elif isinstance(node, list):
        for entry in node:
            found = _find_job_posting(entry)
            if found is not None:
                return found
    return None


def extract_job_posting_json_ld(html: str, *, url: str | None = None) -> dict[str, Any] | None:
    for match in _JSON_LD_PATTERN.finditer(html):
        try:
            parsed = json.loads(match.group(1))
        except json.JSONDecodeError:
            # A malformed unrelated block (e.g. a broken breadcrumb schema) must not sink a
            # good JobPosting block elsewhere on the same page.
            continue
        job_posting = _find_job_posting(parsed)
        if job_posting is not None:
            return job_posting

    logger.error("Rocket Jobs returned unexpected page shape: url=%r", url)
    return None


def _extract_location(raw_job_location: Any) -> str | None:
    entries = raw_job_location if isinstance(raw_job_location, list) else [raw_job_location]

    cities: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw_address = entry.get("address")
        address: dict[str, Any] = raw_address if isinstance(raw_address, dict) else {}
        locality = address.get("addressLocality")
        if locality:
            cities.append(str(locality))

    return ", ".join(cities) if cities else None


def _external_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    return slug or None


class RocketJobsConnector(SitemapDetailPageConnector):
    """Rocket Jobs shares its underlying platform with JustJoin.it -- its sitemap URL even
    redirects to a `public.justjoin.com`-hosted path -- but is ingested independently via
    this separate connector.

    `api.rocketjobs.pl` is a real backend but is deliberately never called: its own
    `robots.txt` disallows crawling it (`Disallow: /` with a marketing-page allowlist that
    does not include the offers endpoint) -- a real operator signal, not just an unmapped
    guess. Instead this connector uses `rocketjobs.pl`'s own published sitemap, which is
    robots.txt-sanctioned and confirmed complete
    (`docs/adr/0025-rocket-jobs-sitemap-and-json-ld-investigation.md`). Like
    `BulldogjobConnector` (P3US38), there is no cursor-paginated endpoint, so this connector
    enumerates every live job URL from the sitemap, then live-fetches each URL's HTML and
    parses its embedded schema.org `JobPosting` JSON-LD block, via the shared
    `SitemapDetailPageConnector` base (US46).
    """

    name = "Rocket Jobs"

    def sitemap_url(self) -> str:
        return ROCKET_JOBS_SITEMAP_URL

    def follow_redirects_on_detail_fetch(self) -> bool:
        # Sitemap-listed URLs occasionally 308-redirect to a canonicalized path (confirmed
        # live 2026-07-14) -- follow so a redirected-but-otherwise-good URL isn't skipped as a
        # broken detail page.
        return True

    def map_offer(self, source_id: int, raw: dict[str, Any]) -> dict[str, Any]:
        raw_org = raw.get("hiringOrganization")
        org: dict[str, Any] = raw_org if isinstance(raw_org, dict) else {}

        raw_salary = raw.get("baseSalary")
        salary: dict[str, Any] = raw_salary if isinstance(raw_salary, dict) else {}
        raw_value = salary.get("value")
        value: dict[str, Any] = raw_value if isinstance(raw_value, dict) else {}
        salary_min, salary_max, salary_currency = normalize_salary(
            ROCKET_JOBS,
            to_int(value.get("minValue")),
            to_int(value.get("maxValue")),
            salary.get("currency"),
        )

        # schema.org JobPosting carries no separate id field (unlike Bulldogjob's job.id).
        # `url` would be the natural field to derive canonical_url/external_id from, but a
        # live sample confirmed 2026-07-14 across several real detail pages never has a `url`
        # key at all -- so this falls back to `_source_url`, which `run`'s `fetch_page`
        # closure sets to the exact sitemap-listed URL the page was fetched from (a value this
        # connector already trusts, not a fabricated one). `url` is checked first only in case
        # a future Rocket Jobs revision starts populating it.
        raw_url = raw.get("url") or raw.get("_source_url")
        canonical_url = raw_url if isinstance(raw_url, str) and raw_url else None

        raw_employment_type = raw.get("employmentType")
        if isinstance(raw_employment_type, list):
            contract_type: str | None = ", ".join(str(t) for t in raw_employment_type) or None
        elif isinstance(raw_employment_type, str) and raw_employment_type:
            contract_type = raw_employment_type
        else:
            contract_type = None

        return {
            "source_id": source_id,
            "external_id": _external_id_from_url(canonical_url),
            "canonical_url": canonical_url,
            "title": raw.get("title") or "",
            "company": org.get("name") or "",
            "location": _extract_location(raw.get("jobLocation")),
            "remote": normalize_remote(ROCKET_JOBS, raw.get("jobLocationType")),
            "seniority": normalize_seniority(ROCKET_JOBS, raw.get("experienceRequirements")),
            "salary_min": salary_min,
            "salary_max": salary_max,
            "salary_currency": salary_currency,
            "contract_type": contract_type,
            "posted_at": raw.get("datePosted"),
            "description": raw.get("description") or None,
        }

    def fetch_sitemap_urls(self, config: dict[str, Any]) -> list[str] | None:
        index_url = self.build_url(config)
        xml_text = fetch_text(index_url, source_name=self.name, logger=logger)
        if xml_text is None:
            return None

        # rocketjobs.pl's sitemap URL redirects through a public.justjoin.com-hosted path
        # straight to its urlset (part0.xml) today, but a `<sitemapindex>` pointing at
        # multiple parts is handled too, in case the site later splits the sitemap.
        urls = parse_sitemap_locs(xml_text, "url")
        if urls:
            return urls

        sub_sitemap_urls = parse_sitemap_locs(xml_text, "sitemap")
        if not sub_sitemap_urls:
            logger.error("Rocket Jobs sitemap had no <url> or <sitemap> entries: url=%r", index_url)
            return None

        all_urls: list[str] = []
        seen: set[str] = set()
        for sub_url in sub_sitemap_urls:
            sub_xml = fetch_text(sub_url, source_name=self.name, logger=logger)
            if sub_xml is None:
                continue
            for url in parse_sitemap_locs(sub_xml, "url"):
                if url not in seen:
                    seen.add(url)
                    all_urls.append(url)

        return all_urls if all_urls else None

    def extract_detail_json(self, html: str, *, url: str | None) -> dict[str, Any] | None:
        parsed = extract_job_posting_json_ld(html, url=url)
        if parsed is None:
            return None
        # `_source_url` is additive provenance (the URL this record was actually fetched
        # from), not a fabricated field -- see map_offer's comment on why canonical_url needs
        # it. It is persisted as part of raw_payload alongside the untouched parsed JSON-LD
        # fields.
        parsed["_source_url"] = url
        return parsed
