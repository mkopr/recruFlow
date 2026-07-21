from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SchedulerRun, Source
from app.schemas.scheduler import SourceStatus


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


async def reconcile_stale_running_runs(session: AsyncSession) -> int:
    """Sweep every `SchedulerRun` still at `status='running'` into `error`.

    `_run_source_async` only ever reaches `finish_run_ok`/`finish_run_error` from inside the
    same coroutine `start_run` began; if the process stops mid-run (crash, hot-reload,
    `docker compose up` recreate) that coroutine is simply gone and nothing else ever
    finalizes the row, so it's orphaned at `running` forever. Must be called once at process
    boot, before `register_jobs` schedules any job -- at that point no run can legitimately
    still be in flight, so every `running` row found here is guaranteed stale, not racing a
    real in-progress run.
    """
    stmt = select(SchedulerRun).where(SchedulerRun.status == "running")
    stale_runs = (await session.scalars(stmt)).all()
    for run in stale_runs:
        run.status = "error"
        run.error_message = "interrupted: process restarted while run was in flight"
        run.finished_at = datetime.now(UTC)
    await session.flush()
    return len(stale_runs)


async def get_latest_run_by_source(session: AsyncSession, source_id: int) -> SchedulerRun | None:
    stmt = (
        select(SchedulerRun)
        .where(SchedulerRun.source_id == source_id)
        .order_by(SchedulerRun.started_at.desc())
        .limit(1)
    )
    result: SchedulerRun | None = await session.scalar(stmt)
    return result


def build_source_status(source: Source, last_run: SchedulerRun | None) -> SourceStatus:
    connector = source.connector
    assert connector is not None
    return SourceStatus(
        source_id=source.id,
        connector=connector,
        name=source.name,
        schedule=(source.config_json or {}).get("schedule", {}),
        fetch_range=(source.config_json or {}).get("fetch_range", {}),
        fetch_scope=(source.config_json or {}).get("fetch_scope", {"mode": "all"}),
        auto_fetch_enabled=(source.config_json or {}).get("auto_fetch_enabled", True),
        connector_enabled=(source.config_json or {}).get("connector_enabled", True),
        last_fetched_at=source.last_fetched_at,
        last_run_id=last_run.id if last_run else None,
        last_run_started_at=last_run.started_at if last_run else None,
        last_run_finished_at=last_run.finished_at if last_run else None,
        last_run_status=last_run.status if last_run else None,
        last_run_trigger_type=last_run.trigger_type if last_run else None,
        last_run_fetched=last_run.fetched_count if last_run else None,
        last_run_created=last_run.created_count if last_run else None,
        last_run_warning=last_run.warning if last_run else False,
        last_run_error_message=last_run.error_message if last_run else None,
    )
