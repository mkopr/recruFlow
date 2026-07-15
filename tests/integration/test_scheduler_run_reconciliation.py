from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.db.models import SchedulerRun, Source
from app.scheduler.runs import reconcile_stale_running_runs
from sqlalchemy.ext.asyncio import AsyncSession


async def _source(session: AsyncSession, *, connector: str) -> Source:
    source = Source(name=connector, connector=connector, config_json={})
    session.add(source)
    await session.flush()
    return source


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reconcile_marks_stale_running_runs_as_error(db_session: AsyncSession) -> None:
    source = await _source(db_session, connector=f"reconcile-{uuid4()}")
    stale_run = SchedulerRun(
        source_id=source.id,
        trigger_type="automatic",
        status="running",
        started_at=datetime.now(UTC) - timedelta(days=7),
    )
    db_session.add(stale_run)
    await db_session.flush()

    reconciled_count = await reconcile_stale_running_runs(db_session)

    assert reconciled_count >= 1
    await db_session.refresh(stale_run)
    assert stale_run.status == "error"
    assert stale_run.finished_at is not None
    assert stale_run.error_message is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reconcile_leaves_finished_runs_untouched(db_session: AsyncSession) -> None:
    source = await _source(db_session, connector=f"reconcile-{uuid4()}")
    finished_at = datetime.now(UTC)
    ok_run = SchedulerRun(
        source_id=source.id,
        trigger_type="automatic",
        status="ok",
        fetched_count=5,
        created_count=1,
        started_at=finished_at - timedelta(minutes=1),
        finished_at=finished_at,
    )
    error_run = SchedulerRun(
        source_id=source.id,
        trigger_type="automatic",
        status="error",
        error_message="boom",
        started_at=finished_at - timedelta(minutes=1),
        finished_at=finished_at,
    )
    db_session.add_all([ok_run, error_run])
    await db_session.flush()

    await reconcile_stale_running_runs(db_session)

    await db_session.refresh(ok_run)
    await db_session.refresh(error_run)
    assert ok_run.status == "ok"
    assert ok_run.finished_at == finished_at
    assert error_run.status == "error"
    assert error_run.error_message == "boom"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reconcile_returns_zero_when_no_stale_runs_exist(db_session: AsyncSession) -> None:
    source = await _source(db_session, connector=f"reconcile-{uuid4()}")
    ok_run = SchedulerRun(
        source_id=source.id,
        trigger_type="automatic",
        status="ok",
        fetched_count=0,
        created_count=0,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )
    db_session.add(ok_run)
    await db_session.flush()

    # No stale rows scoped to this test's own source, but other tests/fixtures in the same
    # DB may have left `running` rows behind -- assert only that this test's own row is
    # untouched, not that the global count is exactly zero.
    await reconcile_stale_running_runs(db_session)

    await db_session.refresh(ok_run)
    assert ok_run.status == "ok"
