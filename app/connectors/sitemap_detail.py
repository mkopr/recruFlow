import asyncio
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.base import JobBoardConnector
from app.connectors.fingerprint import FingerprintPool
from app.connectors.http import BlockedFetchError
from app.connectors.proxy_pool import ProxyPool
from app.connectors.sitemap import next_sitemap_cursor, resolve_sitemap_cursor
from app.db.models import IngestionFailure, Source
from app.dlq.service import build_detail_url_dedup_key, record_failure
from app.dlq.types import FailureType
from app.ingestion.fetch_scope import FETCH_SCOPE_FILTERED, resolve_fetch_scope_terms
from app.ingestion.persist import normalize_and_validate, persist_offer
from app.ingestion.runner import resolve_fetch_range, run_paginated_ingestion
from app.ingestion.types import IngestionResult

DEFAULT_RATE_LIMIT_DELAY_SECONDS = 0.5

_MAX_PROXY_ATTEMPTS = 3

logger = logging.getLogger(__name__)
_proxy_pool = ProxyPool()
_fingerprints = FingerprintPool()


class SitemapDetailPageConnector(JobBoardConnector, ABC):
    """Shared base for connectors with no cursor-paginated endpoint: their real "next page"
    affordance is a client-side call not observable from a plain request. These connectors
    instead enumerate every live job URL from the job board's own sitemap, then live-fetch
    each URL's HTML and parse an embedded per-page JSON blob -- so they need this dedicated
    `run()` shape rather than the inherited cursor-pagination loop (extracted from
    `BulldogjobConnector` and `RocketJobsConnector`, which were ~90% duplicated prior to this
    extraction).
    """

    @abstractmethod
    def sitemap_url(self) -> str: ...

    @abstractmethod
    def fetch_sitemap_urls(self, config: dict[str, Any]) -> list[str] | None: ...

    @abstractmethod
    def extract_detail_json(self, html: str, *, url: str | None) -> dict[str, Any] | None: ...

    def follow_redirects_on_detail_fetch(self) -> bool:
        return False

    def fetch_filtered_sitemap_urls(self, config: dict[str, Any], term: str) -> list[str] | None:
        raise NotImplementedError

    def default_url(self) -> str:
        return self.sitemap_url()

    def build_params(
        self, config: dict[str, Any], *, cursor: Any, page_size: int
    ) -> dict[str, Any]:
        # this connector's fetch shape has no query-parameterized page call
        return {}

    def next_cursor(
        self, payload: Any, offers: list[dict[str, Any]], *, cursor: Any, page_size: int
    ) -> Any | None:
        return None

    def _fetch_detail_html(self, url: str) -> str | None:
        last_status_code: int | None = None
        for attempt in range(1, _MAX_PROXY_ATTEMPTS + 1):
            proxy = _proxy_pool.get_proxy(logger)
            if proxy is None:
                continue

            try:
                response = httpx.get(
                    url,
                    timeout=10.0,
                    headers=_fingerprints.get_headers(),
                    follow_redirects=self.follow_redirects_on_detail_fetch(),
                    proxy=proxy,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                last_status_code = exc.response.status_code
                logger.error(
                    "request failed via proxy %r (attempt %d/%d): url=%r",
                    proxy,
                    attempt,
                    _MAX_PROXY_ATTEMPTS,
                    url,
                    exc_info=True,
                )
                continue
            except httpx.HTTPError:
                last_status_code = None
                logger.error(
                    "request failed via proxy %r (attempt %d/%d): url=%r",
                    proxy,
                    attempt,
                    _MAX_PROXY_ATTEMPTS,
                    url,
                    exc_info=True,
                )
                continue

            return response.text

        logger.error(
            "failed to fetch %s detail page after %d attempts: url=%r",
            self.name,
            _MAX_PROXY_ATTEMPTS,
            url,
        )
        if last_status_code is not None and last_status_code in (403, 429):
            raise BlockedFetchError(last_status_code)
        return None

    async def _run_over_urls(
        self,
        session: AsyncSession,
        source: Source,
        config: dict[str, Any],
        urls: list[str],
        *,
        force_refresh: bool,
        since: datetime | None,
        until: datetime | None,
        persist_cursor: bool = True,
    ) -> IngestionResult:
        # Each "page" is `page_size` live per-URL HTTP fetches, not one batched API call, so
        # these fallback bounds cap total live traffic per run at `page_size * max_pages`
        # (20 * 50 = 1000).
        page_size = int(config.get("page_size", 20))
        max_pages = int(config.get("max_pages", 50))
        already_seen_stop_threshold = int(config.get("already_seen_stop_threshold", 20))
        rate_limit_delay_seconds = float(
            config.get("rate_limit_delay_seconds", DEFAULT_RATE_LIMIT_DELAY_SECONDS)
        )

        # The sitemap order is stable but not recency-sorted, so restarting at cursor 0
        # every run just re-walks the same already-ingested prefix forever. `sitemap_cursor`
        # persists where the previous run left off; `last_cursor` tracks this run's true end
        # (including "reached the end", i.e. `None`) so it can be written back below.
        initial_cursor = resolve_sitemap_cursor(config, len(urls))
        last_cursor: int | None = initial_cursor
        blocked: list[tuple[str, int]] = []

        def fetch_page(
            cursor: int, page_size: int
        ) -> tuple[list[dict[str, Any]], int | None] | None:
            nonlocal last_cursor, blocked
            chunk_urls = urls[cursor : cursor + page_size]
            if not chunk_urls:
                last_cursor = None
                return [], None

            offers: list[dict[str, Any]] = []
            for url in chunk_urls:
                if rate_limit_delay_seconds > 0:
                    time.sleep(rate_limit_delay_seconds)
                try:
                    html = self._fetch_detail_html(url)
                except BlockedFetchError as exc:
                    blocked.append((url, exc.status_code))
                    continue
                if html is None:
                    continue
                parsed = self.extract_detail_json(html, url=url)
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
            # The sitemap isn't sorted newest-first (see ADR 0017) -- a sitemap-order page
            # being wholly older than `since` says nothing about the rest of the catalog, so
            # that early-stop must not apply here.
            sorted_by_recency=False,
        )
        for blocked_url, status_code in blocked:
            await record_failure(
                session,
                IngestionFailure,
                dedup_key=build_detail_url_dedup_key(source.id, blocked_url),
                source_id=source.id,
                url=blocked_url,
                blocked_status=status_code,
                failure_type=FailureType.DETAIL_FETCH_BLOCKED,
                error_message=f"{self.name} detail fetch blocked: HTTP {status_code}",
            )
        if persist_cursor:
            source.config_json = {**config, "sitemap_cursor": next_sitemap_cursor(last_cursor)}
        return result

    async def run(
        self, session: AsyncSession, source: Source, force_refresh: bool = False
    ) -> IngestionResult:
        config = source.config_json or {}
        since, until = resolve_fetch_range(config.get("fetch_range"))

        if self.supports_fetch_scope():
            resolution = await resolve_fetch_scope_terms(session, config)
            if resolution.blocked_reason is not None:
                return IngestionResult(
                    ok=False, fetched=0, created=0, error_message=resolution.blocked_reason
                )
            if resolution.mode == FETCH_SCOPE_FILTERED:
                total_fetched = 0
                total_created = 0
                for term in resolution.terms:
                    try:
                        urls = self.fetch_filtered_sitemap_urls(config, term)
                    except BlockedFetchError as exc:
                        return IngestionResult(
                            ok=False,
                            fetched=total_fetched,
                            created=total_created,
                            error_message=(
                                f"failed to fetch {self.name} offers filtered by {term!r}"
                            ),
                            blocked_status=exc.status_code,
                        )
                    if urls is None:
                        return IngestionResult(
                            ok=False,
                            fetched=total_fetched,
                            created=total_created,
                            error_message=(
                                f"failed to fetch {self.name} offers filtered by {term!r}"
                            ),
                        )
                    result = await self._run_over_urls(
                        session,
                        source,
                        config,
                        urls,
                        force_refresh=force_refresh,
                        since=since,
                        until=until,
                        # Filtered runs enumerate a fresh, per-term, typically-small filtered
                        # listing each time rather than the full stable catalog, so the
                        # "resume where the last run left off" concern doesn't apply here.
                        persist_cursor=False,
                    )
                    total_fetched += result.fetched
                    total_created += result.created
                    if not result.ok:
                        return IngestionResult(
                            ok=False,
                            fetched=total_fetched,
                            created=total_created,
                            error_message=result.error_message,
                        )
                return IngestionResult(ok=True, fetched=total_fetched, created=total_created)

        try:
            urls = self.fetch_sitemap_urls(config)
        except BlockedFetchError as exc:
            return IngestionResult(
                ok=False,
                fetched=0,
                created=0,
                error_message=f"failed to fetch {self.name} offers",
                blocked_status=exc.status_code,
            )
        if urls is None:
            return IngestionResult(
                ok=False, fetched=0, created=0, error_message=f"failed to fetch {self.name} offers"
            )
        return await self._run_over_urls(
            session, source, config, urls, force_refresh=force_refresh, since=since, until=until
        )

    def supports_detail_retry(self) -> bool:
        return True

    async def retry_detail_fetch(self, session: AsyncSession, source: Source, url: str) -> bool:
        # `_fetch_detail_html` is a synchronous, blocking call (proxy-rotated httpx) -- this
        # retry job's tick runs on the main event loop the same way `run_scoring_job` does, so
        # calling it directly here would freeze the whole API exactly as BUG42 found for
        # `run_paginated_ingestion`'s own `fetch_page` call.
        html = await asyncio.to_thread(self._fetch_detail_html, url)
        if html is None:
            return False
        parsed = self.extract_detail_json(html, url=url)
        if parsed is None:
            return False
        mapped = self.map_offer(source.id, parsed)
        offer = await normalize_and_validate(session, mapped)
        if offer is None:
            return False
        await persist_offer(session, offer, parsed)
        return True
