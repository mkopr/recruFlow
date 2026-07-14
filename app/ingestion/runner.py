import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IngestionFailure
from app.dlq.service import record_failure
from app.dlq.types import FailureType
from app.ingestion.persist import ingest_offer
from app.ingestion.types import IngestionResult

FetchPage = Callable[[Any, int], "tuple[list[dict[str, Any]], Any | None] | None"]
MapOffer = Callable[[int, dict[str, Any]], dict[str, Any]]

_POSTED_AT_ADAPTER: TypeAdapter[datetime | None] = TypeAdapter(datetime | None)


def _parse_datetime(value: Any) -> datetime | None:
    """Lenient parse of a raw ISO string, an already-parsed `datetime`, or `None` -- fails
    soft (never raises) on malformed input, same posture as `triggers.py`'s `parse_schedule`.
    """
    try:
        return _POSTED_AT_ADAPTER.validate_python(value)
    except ValidationError:
        return None


def resolve_fetch_range(
    fetch_range: dict[str, Any] | None,
) -> tuple[datetime | None, datetime | None]:
    """Resolve a Source's `config_json["fetch_range"]` into `(since, until)` bounds.

    Fails open to `(None, None)` -- "no filtering" -- for `mode: "all"`, a missing key, or
    any malformed/unrecognised shape (US34's Fetch Range, see `docs/adr/0017`).
    """
    if not isinstance(fetch_range, dict) or fetch_range.get("mode") != "range":
        return None, None
    return _parse_datetime(fetch_range.get("since")), _parse_datetime(fetch_range.get("until"))


async def run_paginated_ingestion(  # noqa: C901
    session: AsyncSession,
    source_id: int,
    *,
    source_name: str,
    fetch_page: FetchPage,
    map_offer: MapOffer,
    initial_cursor: Any,
    page_size: int,
    max_pages: int,
    already_seen_stop_threshold: int,
    force_refresh: bool,
    logger: logging.Logger,
    rate_limit_delay: float = 0.0,
    since: datetime | None = None,
    until: datetime | None = None,
    sorted_by_recency: bool = True,
) -> IngestionResult:
    """Run the fetch -> persist -> early-stop pagination loop shared by all connectors.

    `fetch_page(cursor, page_size)` returns `(raw_items, next_cursor)` on a successful
    fetch, or `None` on transport failure or unexpected response shape -- logging the
    specifics of which is the adapter's job, this loop only distinguishes "first page
    failed" (fatal) from "a later page failed" (keep what was already persisted).
    `next_cursor=None` signals there is no further page to fetch (NoFluffJobs's single-page
    feed always signals this after its one call -- see ADR 0009).

    `since`/`until` (both optional) implement US34's Fetch Range: an offer whose mapped
    `posted_at` falls outside the bounds is skipped -- never persisted, never touching
    `consecutive_already_seen` in either direction -- so a narrow range never looks like
    "we've caught up" and truncates pagination for an unrelated reason. Applies identically
    regardless of `force_refresh` (see `docs/adr/0018`).

    `sorted_by_recency` (default `True`, per ADR 0017's "pagination trusts newest-first
    order" assumption) gates the "whole page older than since cutoff" early-stop: a page
    being entirely older than `since` only proves the rest of the feed is too when the feed
    is actually sorted newest-first. Sitemap-enumeration connectors (Rocket Jobs, Bulldogjob
    -- BUG41) enumerate a stable, non-recency-sorted URL list and must pass `False` so a
    sitemap-order page that happens to be all-older-than-`since` doesn't wrongly truncate the
    rest of the (unsorted) catalog; per-offer range filtering above is unaffected either way.
    """
    total_fetched = 0
    total_created = 0
    consecutive_already_seen = 0
    cursor = initial_cursor
    for page_index in range(max_pages):
        page = fetch_page(cursor, page_size)
        if page is None:
            if page_index == 0:
                return IngestionResult(
                    ok=False,
                    fetched=0,
                    created=0,
                    error_message=f"failed to fetch {source_name} offers",
                )
            logger.warning("%s pagination stopped early after %d page(s)", source_name, page_index)
            await record_failure(
                session,
                IngestionFailure,
                dedup_key=f"source:{source_id}",
                source_id=source_id,
                failure_type=FailureType.PAGE_FETCH_FAILED,
                page=page_index,
                error_message=f"failed to fetch {source_name} page {page_index}",
            )
            break

        offers, cursor = page
        total_fetched += len(offers)

        # Only meaningful when `since` is set and the page is non-empty; flips to False the
        # moment any offer's effective date is not before `since`, including an offer whose
        # date couldn't be determined (see the "now" fallback below) -- so an early stop only
        # ever fires on a page that is unambiguously, entirely older than the cutoff.
        page_all_older_than_since = sorted_by_recency and since is not None and len(offers) > 0

        for raw in offers:
            mapped = map_offer(source_id, raw)

            if since is not None or until is not None:
                posted_at = _parse_datetime(mapped.get("posted_at"))
                # An offer whose posted_at can't be determined is filtered as if it were
                # scraped "now" -- never written back onto the persisted offer, only used for
                # this comparison (ADR 0017). This satisfies both bounds correctly and means
                # such an offer is never mistaken for "old" below.
                effective_date = posted_at if posted_at is not None else datetime.now(UTC)

                if since is not None and effective_date >= since:
                    page_all_older_than_since = False

                if (since is not None and effective_date < since) or (
                    until is not None and effective_date > until
                ):
                    continue

            result = await ingest_offer(session, mapped, raw_payload=raw)
            if result is None:
                continue
            _, created = result
            if created:
                total_created += 1
                consecutive_already_seen = 0
            else:
                consecutive_already_seen += 1

        if since is not None and offers and page_all_older_than_since:
            logger.info(
                "%s pagination stopped early: whole page older than since cutoff", source_name
            )
            break

        if cursor is None:
            break

        # force_refresh bypasses the BUG02/ADR0009 incremental checkpoint: a caller explicitly
        # asking for a fresh fetch wants the full catalog re-walked, not an early exit the moment
        # it looks like we've caught up.
        if not force_refresh and consecutive_already_seen >= already_seen_stop_threshold:
            logger.info(
                "%s pagination stopped early: caught up to %d already-seen offers",
                source_name,
                consecutive_already_seen,
            )
            break

        if rate_limit_delay > 0 and page_index + 1 < max_pages:
            await asyncio.sleep(rate_limit_delay)

    return IngestionResult(ok=True, fetched=total_fetched, created=total_created)
