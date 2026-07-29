from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from app.connectors.http import BlockedFetchError
from app.db.models import IngestionFailure, Source
from app.dlq import retry as dlq_retry_module
from app.dlq.retry import run_detail_retry_batch
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture(autouse=True)
async def _clear_stray_blocked_failures(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    # `run_detail_retry_batch`'s selection query deliberately isn't scoped by connector/source
    # (see its docstring), so it picks up *every* open, sufficiently-old blocked row in the
    # table -- including ones left behind by other integration test files in this same
    # ephemeral `db_test` database that don't clean up after themselves (e.g. the
    # Bulldogjob/Rocket Jobs/Pracuj.pl connector ingestion suites). Those leftover rows'
    # sources have `connector=None` (test fixtures that never set it), which trips this
    # module's own dispatch assert. Clearing them before each test here keeps this file's
    # assertions about *counts* meaningful without weakening the production query.
    await db_session.execute(
        delete(IngestionFailure).where(IngestionFailure.blocked_status.is_not(None))
    )
    await db_session.commit()
    yield


async def _create_source(session: AsyncSession, connector: str) -> int:
    source = Source(name=f"detail-retry-{uuid4()}", connector=connector, config_json={})
    session.add(source)
    await session.flush()
    return source.id


async def _seed_blocked_failure(
    session: AsyncSession,
    *,
    source_id: int,
    url: str | None,
    blocked_status: int | None = 403,
    failure_type: str = "detail_fetch_blocked",
    status: str = "open",
    retry_count: int = 0,
    occurred_at: datetime | None = None,
) -> IngestionFailure:
    row = IngestionFailure(
        source_id=source_id,
        dedup_key=f"source:{source_id}:detail_url:{uuid4()}",
        failure_type=failure_type,
        error_message="blocked",
        status=status,
        url=url,
        blocked_status=blocked_status,
        retry_count=retry_count,
        occurred_at=occurred_at or (datetime.now(UTC) - timedelta(hours=1)),
    )
    session.add(row)
    await session.flush()
    return row


async def _delete_rows(
    session: AsyncSession, *, source_ids: list[int], failure_ids: list[int]
) -> None:
    if failure_ids:
        await session.execute(delete(IngestionFailure).where(IngestionFailure.id.in_(failure_ids)))
    if source_ids:
        await session.execute(delete(Source).where(Source.id.in_(source_ids)))
    await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_detail_retry_batch_end_to_end_resolves_an_eligible_blocked_row(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = f"fake-detail-{uuid4()}"
    source_id = await _create_source(db_session, connector)
    row = await _seed_blocked_failure(db_session, source_id=source_id, url="https://example.test/1")
    await db_session.commit()

    detail_retry = AsyncMock(return_value=True)
    monkeypatch.setattr(
        dlq_retry_module,
        "CONNECTOR_REGISTRY",
        {connector: SimpleNamespace(detail_retry=detail_retry)},
    )

    try:
        summary = await run_detail_retry_batch(db_session, min_age_seconds=60, max_attempts=5)

        assert summary.attempted == 1
        assert summary.resolved == 1
        assert summary.still_blocked == 0
        assert summary.abandoned == 0

        await db_session.refresh(row)
        assert row.status == "resolved"
        assert row.retry_count == 1
    finally:
        await _delete_rows(db_session, source_ids=[source_id], failure_ids=[row.id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_detail_retry_batch_skips_rows_younger_than_min_age(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = f"fake-detail-{uuid4()}"
    source_id = await _create_source(db_session, connector)
    row = await _seed_blocked_failure(
        db_session,
        source_id=source_id,
        url="https://example.test/2",
        occurred_at=datetime.now(UTC),
    )
    await db_session.commit()

    detail_retry = AsyncMock(return_value=True)
    monkeypatch.setattr(
        dlq_retry_module,
        "CONNECTOR_REGISTRY",
        {connector: SimpleNamespace(detail_retry=detail_retry)},
    )

    try:
        summary = await run_detail_retry_batch(db_session, min_age_seconds=3600, max_attempts=5)

        assert summary.attempted == 0
        detail_retry.assert_not_awaited()

        await db_session.refresh(row)
        assert row.status == "open"
        assert row.retry_count == 0
    finally:
        await _delete_rows(db_session, source_ids=[source_id], failure_ids=[row.id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_detail_retry_batch_marks_row_abandoned_at_max_attempts(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = f"fake-detail-{uuid4()}"
    source_id = await _create_source(db_session, connector)
    row = await _seed_blocked_failure(
        db_session, source_id=source_id, url="https://example.test/3", retry_count=5
    )
    await db_session.commit()

    detail_retry = AsyncMock(return_value=True)
    monkeypatch.setattr(
        dlq_retry_module,
        "CONNECTOR_REGISTRY",
        {connector: SimpleNamespace(detail_retry=detail_retry)},
    )

    try:
        summary = await run_detail_retry_batch(db_session, min_age_seconds=60, max_attempts=5)

        assert summary.attempted == 0
        assert summary.abandoned == 1
        detail_retry.assert_not_awaited()

        await db_session.refresh(row)
        assert row.status == "abandoned"
        assert row.retry_count == 5
    finally:
        await _delete_rows(db_session, source_ids=[source_id], failure_ids=[row.id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_detail_retry_batch_increments_retry_count_and_stays_open_when_still_blocked(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = f"fake-detail-{uuid4()}"
    source_id = await _create_source(db_session, connector)
    row = await _seed_blocked_failure(db_session, source_id=source_id, url="https://example.test/4")
    await db_session.commit()

    async def _still_blocked(session: Any, source: Any, url: str) -> bool:
        raise BlockedFetchError(403)

    monkeypatch.setattr(
        dlq_retry_module,
        "CONNECTOR_REGISTRY",
        {connector: SimpleNamespace(detail_retry=_still_blocked)},
    )

    try:
        summary = await run_detail_retry_batch(db_session, min_age_seconds=60, max_attempts=5)

        assert summary.attempted == 1
        assert summary.resolved == 0
        assert summary.still_blocked == 1

        await db_session.refresh(row)
        assert row.status == "open"
        assert row.retry_count == 1
        assert "403" in row.error_message
    finally:
        await _delete_rows(db_session, source_ids=[source_id], failure_ids=[row.id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_detail_retry_batch_ignores_rows_with_null_blocked_status(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = f"fake-detail-{uuid4()}"
    source_id = await _create_source(db_session, connector)
    row = await _seed_blocked_failure(
        db_session,
        source_id=source_id,
        url=None,
        blocked_status=None,
        failure_type="validation_failed",
    )
    await db_session.commit()

    detail_retry = AsyncMock(return_value=True)
    monkeypatch.setattr(
        dlq_retry_module,
        "CONNECTOR_REGISTRY",
        {connector: SimpleNamespace(detail_retry=detail_retry)},
    )

    try:
        summary = await run_detail_retry_batch(db_session, min_age_seconds=60, max_attempts=5)

        assert summary.attempted == 0
        detail_retry.assert_not_awaited()

        refreshed = (
            await db_session.execute(select(IngestionFailure).where(IngestionFailure.id == row.id))
        ).scalar_one()
        assert refreshed.status == "open"
        assert refreshed.retry_count == 0
    finally:
        await _delete_rows(db_session, source_ids=[source_id], failure_ids=[row.id])
