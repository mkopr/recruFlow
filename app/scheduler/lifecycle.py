from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Source
from app.scheduler.service import run_scoring_job_sync, run_source_sync
from app.scheduler.triggers import parse_schedule

SCORING_JOB_ID = "scoring:backlog"


def build_job_id(connector: str) -> str:
    return f"scheduler:{connector}"


def register_scoring_job(scheduler: AsyncIOScheduler, *, interval_seconds: int) -> None:
    """Register the dedicated backlog-draining job, decoupled from every source's own
    ingestion interval (BUG24) -- `max_instances=1` + `coalesce=True` means a run that
    takes longer than `interval_seconds` just chains straight into the next one instead
    of overlapping or piling up missed ticks, so the backlog drains continuously.
    """
    scheduler.add_job(
        run_scoring_job_sync,
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
        if not (source.config_json or {}).get("auto_fetch_enabled", True):
            scheduler.pause_job(job_id)
        count += 1
    return count
