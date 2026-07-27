from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Source
from app.scheduler.runs import build_source_status, get_latest_run_by_source
from app.scheduler.service import run_scoring_job, run_source_sync
from app.scheduler.triggers import parse_schedule
from app.schemas.scheduler import SourceStatus

SCORING_JOB_ID = "scoring:backlog"


def build_job_id(connector: str) -> str:
    return f"scheduler:{connector}"


def connector_should_auto_run(config: dict[str, Any]) -> bool:
    """Whether a Connector's *scheduled* job should be running right now: both
    `connector_enabled` (Connector Stop/Start) and `auto_fetch_enabled` (Auto-Fetch) must be
    true. The two flags are otherwise independent -- this is the one place they're combined,
    so `register_jobs`'s startup pause decision and every enabled/auto-fetch route (single and
    bulk) agree on the same rule instead of each re-deriving it.
    """
    return bool(config.get("connector_enabled", True)) and bool(
        config.get("auto_fetch_enabled", True)
    )


async def apply_auto_run_toggle(
    scheduler: AsyncIOScheduler, session: AsyncSession, source: Source
) -> SourceStatus:
    """Apply `connector_should_auto_run`'s verdict to the live scheduler job for `source`
    (resume/pause) and rebuild its status. One seam for the toggle-application step shared
    by both the single-source and bulk auto-fetch/enabled routes, so a future third
    auto-run flag changes one place instead of four.
    """
    assert source.connector is not None
    job_id = build_job_id(source.connector)
    if connector_should_auto_run(source.config_json or {}):
        scheduler.resume_job(job_id)
    else:
        scheduler.pause_job(job_id)

    last_run = await get_latest_run_by_source(session, source.id)
    return build_source_status(source, last_run)


def register_scoring_job(scheduler: AsyncIOScheduler, *, interval_seconds: int) -> None:
    """Register the dedicated backlog-draining job, decoupled from every source's own
    ingestion interval -- `max_instances=1` + `coalesce=True` means a run that
    takes longer than `interval_seconds` just chains straight into the next one instead
    of overlapping or piling up missed ticks, so the backlog drains continuously.

    Registers the coroutine function `run_scoring_job` directly, not a sync wrapper, so
    `AsyncIOScheduler` runs it on its own event loop instead of a thread-pool worker with a
    fresh loop per tick (see `run_scoring_job`'s docstring).
    """
    scheduler.add_job(
        run_scoring_job,
        trigger=IntervalTrigger(seconds=interval_seconds),
        id=SCORING_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )


async def register_jobs(
    scheduler: AsyncIOScheduler, sessionmaker: async_sessionmaker[AsyncSession]
) -> int:
    async with sessionmaker() as session:
        sources = (await session.scalars(select(Source).where(Source.connector.is_not(None)))).all()

    count = 0
    for source in sources:
        connector = source.connector
        assert connector is not None
        trigger = parse_schedule(source.config_json)
        job_id = build_job_id(connector)
        scheduler.add_job(
            run_source_sync,
            trigger=trigger,
            kwargs={"connector": connector, "trigger_type": "automatic"},
            id=job_id,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        if not connector_should_auto_run(source.config_json or {}):
            scheduler.pause_job(job_id)
        count += 1
    return count
