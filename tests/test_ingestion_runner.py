import logging
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from app.ingestion import runner as runner_module
from app.ingestion.runner import resolve_fetch_range, run_paginated_ingestion


@pytest.mark.asyncio
async def test_run_paginated_ingestion_records_page_fetch_failure_after_first_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_ingest_offer(
        session: object, mapped_fields: dict[str, Any], raw_payload: dict[str, Any]
    ) -> tuple[object, bool]:
        return object(), True

    monkeypatch.setattr(runner_module, "ingest_offer", _fake_ingest_offer)

    pages = {0: ([{"title": "x"}], "cursor1"), 1: None}

    def fetch_page(cursor: Any, page_size: int) -> Any:
        page_index = 0 if cursor is None else 1
        return pages[page_index]

    session = AsyncMock()

    result = await run_paginated_ingestion(
        session,
        source_id=7,
        source_name="test-source",
        fetch_page=fetch_page,
        map_offer=lambda source_id, raw: raw,
        initial_cursor=None,
        page_size=10,
        max_pages=5,
        already_seen_stop_threshold=20,
        force_refresh=False,
        logger=logging.getLogger("test"),
    )

    assert result.ok is True
    session.execute.assert_called_once()
    stmt = session.execute.call_args[0][0]
    assert stmt.table.name == "ingestion_failures"


@pytest.mark.asyncio
async def test_run_paginated_ingestion_first_page_failure_does_not_record_anything() -> None:
    def fetch_page(cursor: Any, page_size: int) -> Any:
        return None

    session = AsyncMock()

    result = await run_paginated_ingestion(
        session,
        source_id=7,
        source_name="test-source",
        fetch_page=fetch_page,
        map_offer=lambda source_id, raw: raw,
        initial_cursor=None,
        page_size=10,
        max_pages=5,
        already_seen_stop_threshold=20,
        force_refresh=False,
        logger=logging.getLogger("test"),
    )

    assert result.ok is False
    session.execute.assert_not_called()


def test_resolve_fetch_range_returns_none_none_for_all_mode() -> None:
    assert resolve_fetch_range({"mode": "all", "since": "2026-01-01T00:00:00Z"}) == (None, None)


def test_resolve_fetch_range_returns_none_none_for_missing_or_malformed_config() -> None:
    assert resolve_fetch_range(None) == (None, None)
    assert resolve_fetch_range({}) == (None, None)
    assert resolve_fetch_range({"mode": "bogus"}) == (None, None)


def test_resolve_fetch_range_parses_since_and_until_for_range_mode() -> None:
    since, until = resolve_fetch_range(
        {"mode": "range", "since": "2026-01-01T00:00:00Z", "until": "2026-01-08T00:00:00Z"}
    )
    assert since == datetime(2026, 1, 1, tzinfo=UTC)
    assert until == datetime(2026, 1, 8, tzinfo=UTC)


@pytest.mark.asyncio
async def test_run_paginated_ingestion_skips_offers_outside_range_without_persisting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def _fake_ingest_offer(
        session: object, mapped_fields: dict[str, Any], raw_payload: dict[str, Any]
    ) -> tuple[object, bool]:
        calls.append(mapped_fields)
        return object(), True

    monkeypatch.setattr(runner_module, "ingest_offer", _fake_ingest_offer)

    offers = [
        {"title": "in-range", "posted_at": "2026-06-15T00:00:00Z"},
        {"title": "out-of-range", "posted_at": "2026-05-01T00:00:00Z"},
    ]

    def fetch_page(cursor: Any, page_size: int) -> Any:
        return (offers, None) if cursor is None else None

    session = AsyncMock()

    result = await run_paginated_ingestion(
        session,
        source_id=7,
        source_name="test-source",
        fetch_page=fetch_page,
        map_offer=lambda source_id, raw: raw,
        initial_cursor=None,
        page_size=10,
        max_pages=5,
        already_seen_stop_threshold=20,
        force_refresh=False,
        logger=logging.getLogger("test"),
        since=datetime(2026, 6, 1, tzinfo=UTC),
        until=datetime(2026, 6, 30, tzinfo=UTC),
    )

    assert result.fetched == 2
    assert result.created == 1
    assert len(calls) == 1
    assert calls[0]["title"] == "in-range"


@pytest.mark.asyncio
async def test_run_paginated_ingestion_out_of_range_offers_do_not_trip_already_seen_early_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_ingest_offer(
        session: object, mapped_fields: dict[str, Any], raw_payload: dict[str, Any]
    ) -> tuple[object, bool]:
        return object(), True

    monkeypatch.setattr(runner_module, "ingest_offer", _fake_ingest_offer)

    # Both offers on page 1 are *newer* than `until` (not older than `since`), so they are
    # filtered out by the upper bound without ever looking like a wholly-stale page -- this
    # isolates the already-seen bookkeeping from the sort-order early-stop optimization.
    page1_offers = [
        {"title": "future-1", "posted_at": "2026-07-15T00:00:00Z"},
        {"title": "future-2", "posted_at": "2026-07-16T00:00:00Z"},
    ]
    page2_offers = [{"title": "in-range", "posted_at": "2026-06-15T00:00:00Z"}]
    fetch_calls: list[Any] = []

    def fetch_page(cursor: Any, page_size: int) -> Any:
        fetch_calls.append(cursor)
        if cursor is None:
            return page1_offers, "cursor1"
        if cursor == "cursor1":
            return page2_offers, None
        raise AssertionError("fetch_page should not be called beyond page 2")

    session = AsyncMock()

    result = await run_paginated_ingestion(
        session,
        source_id=7,
        source_name="test-source",
        fetch_page=fetch_page,
        map_offer=lambda source_id, raw: raw,
        initial_cursor=None,
        page_size=10,
        max_pages=5,
        already_seen_stop_threshold=2,
        force_refresh=False,
        logger=logging.getLogger("test"),
        since=datetime(2026, 6, 1, tzinfo=UTC),
        until=datetime(2026, 6, 30, tzinfo=UTC),
    )

    assert len(fetch_calls) == 2
    assert result.fetched == 3
    assert result.created == 1


@pytest.mark.asyncio
async def test_run_paginated_ingestion_since_and_until_none_reproduces_existing_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_ingest_offer(
        session: object, mapped_fields: dict[str, Any], raw_payload: dict[str, Any]
    ) -> tuple[object, bool]:
        return object(), True

    monkeypatch.setattr(runner_module, "ingest_offer", _fake_ingest_offer)

    pages = {0: ([{"title": "x"}], "cursor1"), 1: None}

    def fetch_page(cursor: Any, page_size: int) -> Any:
        page_index = 0 if cursor is None else 1
        return pages[page_index]

    session = AsyncMock()

    result = await run_paginated_ingestion(
        session,
        source_id=7,
        source_name="test-source",
        fetch_page=fetch_page,
        map_offer=lambda source_id, raw: raw,
        initial_cursor=None,
        page_size=10,
        max_pages=5,
        already_seen_stop_threshold=20,
        force_refresh=False,
        logger=logging.getLogger("test"),
    )

    assert result.ok is True
    session.execute.assert_called_once()
    stmt = session.execute.call_args[0][0]
    assert stmt.table.name == "ingestion_failures"


@pytest.mark.asyncio
async def test_run_paginated_ingestion_offer_with_unparseable_posted_at_is_kept_in_range_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def _fake_ingest_offer(
        session: object, mapped_fields: dict[str, Any], raw_payload: dict[str, Any]
    ) -> tuple[object, bool]:
        calls.append(mapped_fields)
        return object(), True

    monkeypatch.setattr(runner_module, "ingest_offer", _fake_ingest_offer)

    offers = [{"title": "undated", "posted_at": "not-a-date"}]

    def fetch_page(cursor: Any, page_size: int) -> Any:
        return (offers, None) if cursor is None else None

    session = AsyncMock()

    # No `until` bound and a `since` safely in the past: the "now" fallback for an
    # unparseable posted_at is guaranteed to satisfy both, making this deterministic.
    result = await run_paginated_ingestion(
        session,
        source_id=7,
        source_name="test-source",
        fetch_page=fetch_page,
        map_offer=lambda source_id, raw: raw,
        initial_cursor=None,
        page_size=10,
        max_pages=5,
        already_seen_stop_threshold=20,
        force_refresh=False,
        logger=logging.getLogger("test"),
        since=datetime(2020, 1, 1, tzinfo=UTC),
        until=None,
    )

    assert len(calls) == 1
    assert result.created == 1


@pytest.mark.asyncio
async def test_run_paginated_ingestion_stops_early_when_whole_page_is_older_than_since(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_ingest_offer(
        session: object, mapped_fields: dict[str, Any], raw_payload: dict[str, Any]
    ) -> tuple[object, bool]:
        return object(), True

    monkeypatch.setattr(runner_module, "ingest_offer", _fake_ingest_offer)

    page1_offers = [
        {"title": "old-1", "posted_at": "2026-01-01T00:00:00Z"},
        {"title": "old-2", "posted_at": "2026-01-02T00:00:00Z"},
    ]

    def fetch_page(cursor: Any, page_size: int) -> Any:
        if cursor is None:
            return page1_offers, "cursor1"
        raise AssertionError("fetch_page should have stopped before requesting page 2")

    session = AsyncMock()

    result = await run_paginated_ingestion(
        session,
        source_id=7,
        source_name="test-source",
        fetch_page=fetch_page,
        map_offer=lambda source_id, raw: raw,
        initial_cursor=None,
        page_size=10,
        max_pages=5,
        already_seen_stop_threshold=20,
        force_refresh=False,
        logger=logging.getLogger("test"),
        since=datetime(2026, 6, 1, tzinfo=UTC),
        until=None,
    )

    assert result.fetched == 2
    assert result.created == 0


@pytest.mark.asyncio
async def test_run_paginated_ingestion_sorted_by_recency_false_keeps_paging_past_old_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_ingest_offer(
        session: object, mapped_fields: dict[str, Any], raw_payload: dict[str, Any]
    ) -> tuple[object, bool]:
        return object(), True

    monkeypatch.setattr(runner_module, "ingest_offer", _fake_ingest_offer)

    # Same shape as the "stops early" test above, but this feed (like Rocket Jobs/Bulldogjob's
    # sitemap enumeration, BUG41) isn't sorted newest-first -- page 1 being wholly older than
    # `since` must not be trusted as proof the rest of the feed is too.
    page1_offers = [
        {"title": "old-1", "posted_at": "2026-01-01T00:00:00Z"},
        {"title": "old-2", "posted_at": "2026-01-02T00:00:00Z"},
    ]
    page2_offers = [{"title": "new-1", "posted_at": "2026-06-15T00:00:00Z"}]

    def fetch_page(cursor: Any, page_size: int) -> Any:
        if cursor is None:
            return page1_offers, "cursor1"
        if cursor == "cursor1":
            return page2_offers, None
        raise AssertionError("unexpected cursor")

    session = AsyncMock()

    result = await run_paginated_ingestion(
        session,
        source_id=7,
        source_name="test-source",
        fetch_page=fetch_page,
        map_offer=lambda source_id, raw: raw,
        initial_cursor=None,
        page_size=10,
        max_pages=5,
        already_seen_stop_threshold=20,
        force_refresh=False,
        logger=logging.getLogger("test"),
        since=datetime(2026, 6, 1, tzinfo=UTC),
        until=None,
        sorted_by_recency=False,
    )

    assert result.fetched == 3
    assert result.created == 1
