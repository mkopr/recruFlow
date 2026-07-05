import asyncio
import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.persist import ingest_offer
from app.ingestion.types import IngestionResult

FetchPage = Callable[[Any, int], "tuple[list[dict[str, Any]], Any | None] | None"]
MapOffer = Callable[[int, dict[str, Any]], dict[str, Any]]


async def run_paginated_ingestion(
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
) -> IngestionResult:
    """Run the fetch -> persist -> early-stop pagination loop shared by all connectors.

    `fetch_page(cursor, page_size)` returns `(raw_items, next_cursor)` on a successful
    fetch, or `None` on transport failure or unexpected response shape -- logging the
    specifics of which is the adapter's job, this loop only distinguishes "first page
    failed" (fatal) from "a later page failed" (keep what was already persisted).
    `next_cursor=None` signals there is no further page to fetch (NoFluffJobs's single-page
    feed always signals this after its one call -- see ADR 0009).
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
            break

        offers, cursor = page
        total_fetched += len(offers)

        for raw in offers:
            mapped = map_offer(source_id, raw)
            result = await ingest_offer(session, mapped, raw_payload=raw)
            if result is None:
                continue
            _, created = result
            if created:
                total_created += 1
                consecutive_already_seen = 0
            else:
                consecutive_already_seen += 1

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
