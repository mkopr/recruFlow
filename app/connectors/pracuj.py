import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.base import JobBoardConnector
from app.db.models import IngestionFailure, Source
from app.dlq.service import record_failure
from app.dlq.types import FailureType
from app.ingestion.fetch_scope import resolve_fetch_scope_terms
from app.ingestion.normalize import (
    PRACUJ,
    normalize_remote,
    normalize_salary,
    normalize_seniority,
    to_int,
)
from app.ingestion.runner import resolve_fetch_range, run_paginated_ingestion
from app.ingestion.types import IngestionResult

PRACUJ_HOMEPAGE_URL = "https://www.pracuj.pl/"
PRACUJ_LISTING_URL_TEMPLATE = "https://www.pracuj.pl/praca/{keyword};kw"

# Browser-driven fetching is far more expensive than a plain HTTP connector's page call, so
# this connector's defaults are deliberately smaller/slower than every other connector's
# (rate_limit_delay unset, page_size=100) -- the same "expensive, throttle hard" rationale
# ADR 0026 already established for this operator's Cloudflare tuning.
DEFAULT_RATE_LIMIT_DELAY_SECONDS = 4.0
DEFAULT_PAGE_SIZE = 10
DEFAULT_MAX_PAGES = 5

_DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_NEXT_DATA_PATTERN = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)
_CHALLENGE_MARKERS = ("Just a moment", "cf-mitigated", "Enable JavaScript and cookies")

# Pracuj.pl's own salary API shape (confirmed live 2026-07-14): a `typesOfContracts[].salary`
# block's `timeUnit.id` is `0` for a monthly figure, non-zero (`1` observed for hourly B2B
# rates) otherwise. Mixing an hourly rate (~140 zl/godz.) into salary_min/max meant for a
# monthly figure would silently corrupt every downstream comparison, so only a monthly-rate
# contract type's salary is ever used for salary_min/max.
_MONTHLY_TIME_UNIT_ID = 0

FetchHtml = Callable[[str], Awaitable[str | None]]

logger = logging.getLogger(__name__)


def _is_challenge_page(html: str) -> bool:
    return any(marker.lower() in html.lower() for marker in _CHALLENGE_MARKERS)


async def _fetch_rendered_page(page: Page, url: str, *, timeout: float = 15.0) -> str | None:
    """Navigate `page` to `url` and return its rendered HTML, or `None` on any failure --
    transport error, timeout, non-2xx status, or a Cloudflare Managed Challenge page in place
    of real content. Same failure contract as `app/connectors/http.py`'s `fetch_text`/
    `fetch_json`: log via `exc_info=True`, return `None`, never raise.
    """
    try:
        resp = await page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
        if resp is None:
            logger.error("failed to fetch Pracuj.pl page: url=%r (no response)", url)
            return None
        html = await resp.text()
    except (PlaywrightError, PlaywrightTimeoutError):
        logger.error("failed to fetch Pracuj.pl page: url=%r", url, exc_info=True)
        return None

    if resp.status >= 400:
        logger.error("failed to fetch Pracuj.pl page: url=%r status=%r", url, resp.status)
        return None
    if _is_challenge_page(html):
        logger.error("Pracuj.pl challenge page encountered: url=%r", url)
        return None
    return html


def extract_next_data(html: str, *, url: str | None = None) -> dict[str, Any] | None:
    match = _NEXT_DATA_PATTERN.search(html)
    if match is None:
        logger.error("Pracuj.pl returned unexpected page shape: url=%r", url)
        return None
    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError:
        logger.error("Pracuj.pl returned unexpected page shape: url=%r", url)
        return None
    return parsed if isinstance(parsed, dict) else None


def _dehydrated_query_data(next_data: dict[str, Any], query_key_prefix: str) -> Any | None:
    """Pracuj.pl's Next.js pages embed their real content as a React Query SSR cache
    (`props.pageProps.dehydratedState.queries`) rather than a single top-level data blob --
    each query is keyed by a list whose first element names the query (`"jobOffers"` on a
    search-listing page, `"jobOffer"` on a detail page; confirmed live 2026-07-14).
    """
    page_props = next_data.get("props", {})
    pp: dict[str, Any] = page_props.get("pageProps", {}) if isinstance(page_props, dict) else {}
    dehydrated = pp.get("dehydratedState", {}) if isinstance(pp, dict) else {}
    queries = dehydrated.get("queries", []) if isinstance(dehydrated, dict) else []
    if not isinstance(queries, list):
        return None
    for query in queries:
        if not isinstance(query, dict):
            continue
        key = query.get("queryKey")
        if isinstance(key, list) and key and key[0] == query_key_prefix:
            state = query.get("state", {})
            return state.get("data") if isinstance(state, dict) else None
    return None


async def _fetch_listing_page(
    fetch_html: FetchHtml, listing_url: str
) -> list[dict[str, Any]] | None:
    """Fetch and parse one search-listing page, returning its `groupedOffers` list (possibly
    empty, meaning "no more results") or `None` on any fetch/parse failure.
    """
    html = await fetch_html(listing_url)
    if html is None:
        return None

    next_data = extract_next_data(html, url=listing_url)
    job_data = _dehydrated_query_data(next_data, "jobOffers") if next_data else None
    grouped = job_data.get("groupedOffers") if isinstance(job_data, dict) else None
    return grouped if isinstance(grouped, list) else None


async def _fetch_offer_details(
    fetch_html: FetchHtml,
    candidate_urls: list[str],
    *,
    collected: list[dict[str, Any]],
    total_cap: int,
    rate_limit_delay_seconds: float,
) -> None:
    """Detail-fetches each URL in `candidate_urls`, appending successfully parsed records to
    `collected` in place. A failed fetch (`fetch_html` returned `None`, already logged by
    `_fetch_rendered_page`) or a malformed-but-fetched record is skipped, not fatal -- mirrors
    Bulldogjob/Rocket Jobs's per-URL `if html is None: continue` (`sitemap_detail.py`). This
    used to abort the whole page on the first failed detail fetch, back when this
    connector shared one browser context across an entire run and Cloudflare's challenge meant
    a failure there really did mean every later request in the run was doomed too. Now that
    `run` opens a fresh context per fetch, a single failure is just as likely to be an ordinary
    transient hiccup (confirmed live: 25/25 fresh-context detail fetches succeeded in a row) as
    a real block, so skipping it and continuing gets far more of an already-fetched listing
    page's offers collected per run instead of throwing all of them away.
    """
    for detail_url in candidate_urls:
        if len(collected) >= total_cap:
            return

        await asyncio.sleep(rate_limit_delay_seconds)
        detail_html = await fetch_html(detail_url)
        if detail_html is None:
            continue

        detail_data = extract_next_data(detail_html, url=detail_url)
        offer_record = _dehydrated_query_data(detail_data, "jobOffer") if detail_data else None
        if isinstance(offer_record, dict):
            collected.append(offer_record)


async def _collect_offers(
    fetch_html: FetchHtml,
    *,
    category_filter: str,
    start_page: int,
    page_size: int,
    max_pages: int,
    rate_limit_delay_seconds: float,
) -> tuple[list[dict[str, Any]], bool, bool, int]:
    """Enumerate offer URLs from Pracuj.pl's keyword-filtered search listing (`;kw`, applying
    `category_filter` at enumeration time -- Pracuj.pl's own published sitemap
    (`SiteMaps/CurrentOffers/SiteMapIndexJobOffers.xml`, robots.txt-listed) was found live
    2026-07-14 to be stale (every sub-sitemap's `lastmod` from Nov/Dec 2021), so listing-page
    pagination replaces it as the enumeration source -- then fetches each offer's own detail
    page for the richer structured record (numeric salary, boolean remote flag) `map_offer`
    needs, applying `rate_limit_delay_seconds` before every fetch.

    `start_page` resumes enumeration from a previous run's persisted `listing_page_cursor`
    (the same class of gap fixed for Rocket Jobs/Bulldogjob's sitemap
    enumeration): starting at page 1 every run meant every hourly tick re-crawled and
    deduped-away the same first `page_size * max_pages` listings forever, never reaching the
    rest of the category's results.

    Returns `(offers, enumeration_ok, mid_run_failure, next_start_page)`. `enumeration_ok=False`
    means the first listing-page fetch itself failed -- `run` maps this straight to
    `IngestionResult(ok=False, ...)`, and `next_start_page` is meaningless in that case.
    `mid_run_failure=True` means a *later listing-page* fetch failed after that (page 2+ of this
    run) -- unlike an individual detail fetch (see `_fetch_offer_details`'s docstring),
    losing the listing page itself means there's no way to know what the rest of that page's
    offer URLs even were, so collection stops there rather than guessing; whatever was already
    collected is still returned so it gets persisted, and `next_start_page` points back at the
    page that failed so the next run retries it rather than skipping past unseen listings.
    `next_start_page` is `1` (wrap for a fresh pass) when an empty or short page proved the
    listing is genuinely exhausted, or `start_page`+pages-actually-consumed otherwise (the
    listing has more pages this run didn't get to yet).
    """
    collected: list[dict[str, Any]] = []
    total_cap = page_size * max_pages
    listing_url_base = PRACUJ_LISTING_URL_TEMPLATE.format(keyword=quote(category_filter, safe=""))

    last_page_num = start_page - 1
    for listing_page_num in range(start_page, start_page + max_pages):
        if len(collected) >= total_cap:
            break

        if listing_page_num > start_page:
            await asyncio.sleep(rate_limit_delay_seconds)
        listing_url = f"{listing_url_base}?pn={listing_page_num}&rop={page_size}"
        grouped = await _fetch_listing_page(fetch_html, listing_url)
        if grouped is None:
            if listing_page_num == start_page:
                return [], False, False, start_page
            return collected, True, True, listing_page_num

        if not grouped:
            return collected, True, False, 1  # empty page -- clean end, wrap for next pass

        candidate_urls = [
            sub_offer["offerAbsoluteUri"]
            for group in grouped
            if isinstance(group, dict)
            for sub_offer in (group.get("offers") or [])
            if isinstance(sub_offer, dict) and sub_offer.get("offerAbsoluteUri")
        ]

        await _fetch_offer_details(
            fetch_html,
            candidate_urls,
            collected=collected,
            total_cap=total_cap,
            rate_limit_delay_seconds=rate_limit_delay_seconds,
        )

        last_page_num = listing_page_num
        if len(grouped) < page_size:
            return collected, True, False, 1  # short page -- reached the end, wrap

    return collected, True, False, last_page_num + 1


def _pick_monthly_salary(
    types_of_contracts: list[Any],
) -> tuple[dict[str, Any], str | None, bool | None]:
    """Prefers a UoP ("umowa o pracę") monthly-rate salary block, falling back to any other
    monthly-rate contract type in list order. An hourly-rate block (typically B2B) is never
    used for salary_min/max -- see `_MONTHLY_TIME_UNIT_ID`'s comment -- but its contract-type
    name is still reported as a fallback `contract_type` when no monthly figure exists at all.
    """
    monthly: list[dict[str, Any]] = []
    all_names: list[str] = []
    for entry in types_of_contracts:
        if not isinstance(entry, dict):
            continue
        name = entry.get("pracujPlName") or entry.get("name")
        if name:
            all_names.append(str(name))
        salary = entry.get("salary")
        if isinstance(salary, dict):
            time_unit = salary.get("timeUnit")
            if isinstance(time_unit, dict) and time_unit.get("id") == _MONTHLY_TIME_UNIT_ID:
                monthly.append(entry)

    if not monthly:
        return {}, (all_names[0] if all_names else None), None

    preferred = next(
        (e for e in monthly if "umowa o pracę" in str(e.get("pracujPlName", "")).lower()),
        monthly[0],
    )
    raw_salary = preferred.get("salary")
    preferred_salary: dict[str, Any] = raw_salary if isinstance(raw_salary, dict) else {}
    name = preferred.get("pracujPlName") or preferred.get("name")
    salary_kind = preferred_salary.get("salaryKind")
    code = salary_kind.get("code") if isinstance(salary_kind, dict) else None
    raw_gross = (code == "gross") if code else None
    return preferred_salary, (str(name) if name else None), raw_gross


class PracujConnector(JobBoardConnector):
    """Pracuj.pl (operated by Grupa Pracuj, the same operator as `RocketJobsConnector`'s
    Rocket Jobs and the abandoned The Protocol spike) fronts Cloudflare's Managed Challenge on
    every plain-HTTP path -- homepage, API guesses, even its own robots.txt-listed sitemap
    (confirmed live 2026-07-14). Unlike every other connector in this registry, there is no
    HTTP fallback: `docs/adr/0026-pracuj-playwright-cloudflare-feasibility-spike.md` confirmed
    stock Playwright Chromium clears the challenge cleanly and repeatedly, so this connector's
    entire fetch path -- enumeration and detail alike -- goes through a Playwright browser
    context. One browser *process* is launched per run and reused, but each fetch gets its own
    fresh context (the challenge allows exactly one clean navigation per context before
    blocking every later request in it, so context reuse across fetches silently zeroed out
    every automated run).

    Given Pracuj.pl spans every industry, not just IT, `config_json["category_filter"]`
    (default `"it"`, mirroring `SolidJobsConnector`'s `division` config) is applied at
    enumeration time via Pracuj.pl's own keyword-search URL (`/praca/{keyword};kw`) so a
    non-matching offer is never even detail-fetched, let alone ingested.
    """

    name = "Pracuj.pl"

    def default_url(self) -> str:
        return PRACUJ_HOMEPAGE_URL

    def build_params(
        self, config: dict[str, Any], *, cursor: Any, page_size: int
    ) -> dict[str, Any]:
        # Pracuj.pl's fetch shape is entirely browser-driven -- see class docstring.
        return {}

    def next_cursor(
        self, payload: Any, offers: list[dict[str, Any]], *, cursor: Any, page_size: int
    ) -> Any | None:
        return None

    def supports_fetch_scope(self) -> bool:
        return True

    def map_offer(self, source_id: int, raw: dict[str, Any]) -> dict[str, Any]:
        raw_attrs = raw.get("attributes")
        attrs: dict[str, Any] = raw_attrs if isinstance(raw_attrs, dict) else {}

        raw_employment = attrs.get("employment")
        employment: dict[str, Any] = raw_employment if isinstance(raw_employment, dict) else {}

        raw_types_of_contracts = employment.get("typesOfContracts")
        salary, contract_type, raw_gross = _pick_monthly_salary(
            raw_types_of_contracts if isinstance(raw_types_of_contracts, list) else []
        )
        raw_currency = salary.get("currency") if salary else None
        currency_code = raw_currency.get("code") if isinstance(raw_currency, dict) else None
        salary_min, salary_max, salary_currency = normalize_salary(
            PRACUJ,
            to_int(salary.get("from")),
            to_int(salary.get("to")),
            currency_code,
            raw_gross=raw_gross,
        )

        raw_position_levels = employment.get("positionLevels")
        seniority_labels = (
            [
                str(level["pracujPlName"] if level.get("pracujPlName") else level.get("name"))
                for level in raw_position_levels
                if isinstance(level, dict) and (level.get("pracujPlName") or level.get("name"))
            ]
            if isinstance(raw_position_levels, list)
            else None
        )

        raw_workplaces = attrs.get("workplaces")
        location = (
            ", ".join(
                str(workplace["displayAddress"])
                for workplace in raw_workplaces
                if isinstance(workplace, dict) and workplace.get("displayAddress")
            )
            if isinstance(raw_workplaces, list) and raw_workplaces
            else None
        )

        job_offer_web_id = raw.get("jobOfferWebId")

        raw_publication_details = raw.get("publicationDetails")
        publication_details: dict[str, Any] = (
            raw_publication_details if isinstance(raw_publication_details, dict) else {}
        )

        return {
            "source_id": source_id,
            "external_id": str(job_offer_web_id) if job_offer_web_id is not None else None,
            "canonical_url": attrs.get("offerAbsoluteUrl") or None,
            "title": attrs.get("jobTitle") or "",
            "company": attrs.get("displayEmployerName") or "",
            "location": location,
            "remote": normalize_remote(PRACUJ, employment.get("entirelyRemoteWork")),
            "seniority": normalize_seniority(PRACUJ, seniority_labels),
            "salary_min": salary_min,
            "salary_max": salary_max,
            "salary_currency": salary_currency,
            "contract_type": contract_type,
            "posted_at": publication_details.get("dateOfInitialPublicationUtc"),
            "description": attrs.get("description") or None,
        }

    async def run(
        self, session: AsyncSession, source: Source, force_refresh: bool = False
    ) -> IngestionResult:
        config = source.config_json or {}
        since, until = resolve_fetch_range(config.get("fetch_range"))
        category_filter = str(config.get("category_filter") or "it")
        page_size = int(config.get("page_size", DEFAULT_PAGE_SIZE))
        max_pages = int(config.get("max_pages", DEFAULT_MAX_PAGES))
        already_seen_stop_threshold = int(config.get("already_seen_stop_threshold", 20))
        rate_limit_delay_seconds = float(
            config.get("rate_limit_delay_seconds", DEFAULT_RATE_LIMIT_DELAY_SECONDS)
        )
        # Pracuj.pl's search-listing enumeration has the same stable-but-not-recency-
        # sorted shape as Rocket Jobs/Bulldogjob's sitemaps -- resume from where the
        # last run left off instead of re-crawling page 1 every time.
        start_page = int(config.get("listing_page_cursor", 1) or 1)
        if start_page < 1:
            start_page = 1

        # Fetch Scope: a cheap short-circuit before launching Chromium for a run that's
        # going to be blocked anyway.
        scope_resolution = await resolve_fetch_scope_terms(session, config)
        if scope_resolution.blocked_reason is not None:
            return IngestionResult(
                ok=False, fetched=0, created=0, error_message=scope_resolution.blocked_reason
            )
        filtered_terms = scope_resolution.terms  # empty means mode == "all", unchanged behavior

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:

                async def fetch_html(url: str) -> str | None:
                    # Cloudflare's Managed Challenge on this zone lets exactly one
                    # clean navigation through per browser context, then blocks (403,
                    # challenge page) every later request in that same context regardless
                    # of delay -- confirmed live 2026-07-15 by reproducing listing-then-
                    # detail (and even listing-then-listing) fetches back to back. A fresh
                    # context per fetch resets that budget without the much higher cost of
                    # relaunching the whole browser process for every page/offer.
                    context = await browser.new_context(
                        user_agent=_DESKTOP_USER_AGENT, locale="pl-PL"
                    )
                    try:
                        page = await context.new_page()
                        return await _fetch_rendered_page(page, url)
                    finally:
                        await context.close()

                if filtered_terms:
                    # Filtered runs don't participate in the listing_page_cursor
                    # resumption -- always start_page=1 per term, a deliberate scope
                    # reduction documented alongside Bulldogjob's own filtered-mode gap
                    # (docs/adr/0027).
                    offers: list[dict[str, Any]] = []
                    enumeration_ok = False
                    mid_run_failure = False
                    for term in filtered_terms:
                        (
                            term_offers,
                            term_enumeration_ok,
                            term_mid_run_failure,
                            _term_next_start_page,
                        ) = await _collect_offers(
                            fetch_html,
                            category_filter=term,
                            start_page=1,
                            page_size=page_size,
                            max_pages=max_pages,
                            rate_limit_delay_seconds=rate_limit_delay_seconds,
                        )
                        # Cross-term duplicate detail records are harmless -- ingest_offer's
                        # canonical-URL dedup collapses them at persist time.
                        offers.extend(term_offers)
                        enumeration_ok = enumeration_ok or term_enumeration_ok
                        mid_run_failure = mid_run_failure or term_mid_run_failure
                    next_start_page = None
                else:
                    (
                        offers,
                        enumeration_ok,
                        mid_run_failure,
                        next_start_page,
                    ) = await _collect_offers(
                        fetch_html,
                        category_filter=category_filter,
                        start_page=start_page,
                        page_size=page_size,
                        max_pages=max_pages,
                        rate_limit_delay_seconds=rate_limit_delay_seconds,
                    )
            finally:
                await browser.close()

        if not enumeration_ok:
            return IngestionResult(
                ok=False, fetched=0, created=0, error_message=f"failed to fetch {self.name} offers"
            )

        if mid_run_failure:
            await record_failure(
                session,
                IngestionFailure,
                dedup_key=f"source:{source.id}",
                source_id=source.id,
                failure_type=FailureType.PAGE_FETCH_FAILED,
                error_message=f"failed to fetch {self.name} page mid-run",
            )

        def fetch_page(
            cursor: int, page_size: int
        ) -> tuple[list[dict[str, Any]], int | None] | None:
            chunk = offers[cursor : cursor + page_size]
            next_cursor = cursor + page_size if cursor + page_size < len(offers) else None
            return chunk, next_cursor

        result = await run_paginated_ingestion(
            session,
            source.id,
            source_name=self.name,
            fetch_page=fetch_page,
            map_offer=self.map_offer,
            initial_cursor=0,
            page_size=page_size,
            max_pages=max_pages,
            already_seen_stop_threshold=already_seen_stop_threshold,
            force_refresh=force_refresh,
            logger=logger,
            since=since,
            until=until,
            # Pracuj.pl's search-listing order isn't recency-sorted either (see ADR
            # 0017) -- a wholly-stale prefetched batch says nothing about the rest of the
            # (already fully prefetched) listing.
            sorted_by_recency=False,
        )
        if not filtered_terms:
            source.config_json = {**config, "listing_page_cursor": next_start_page}
        return result
