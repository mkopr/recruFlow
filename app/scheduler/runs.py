from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SchedulerRun


async def start_run(session: AsyncSession, source_id: int, *, trigger_type: str) -> SchedulerRun:
    run = SchedulerRun(
        source_id=source_id,
        trigger_type=trigger_type,
        status="running",
        started_at=datetime.now(UTC),
    )
    session.add(run)
    await session.flush()
    return run


async def finish_run_ok(
    session: AsyncSession, run: SchedulerRun, *, fetched: int, created: int, warning: bool
) -> None:
    run.status = "ok"
    run.fetched_count = fetched
    run.created_count = created
    run.warning = warning
    run.finished_at = datetime.now(UTC)
    await session.flush()


async def finish_run_error(session: AsyncSession, run: SchedulerRun, *, error_message: str) -> None:
    run.status = "error"
    run.error_message = error_message
    run.finished_at = datetime.now(UTC)
    await session.flush()


async def get_latest_run_by_source(session: AsyncSession, source_id: int) -> SchedulerRun | None:
    stmt = (
        select(SchedulerRun)
        .where(SchedulerRun.source_id == source_id)
        .order_by(SchedulerRun.started_at.desc())
        .limit(1)
    )
    result: SchedulerRun | None = await session.scalar(stmt)
    return result
