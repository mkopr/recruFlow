from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Source
from app.scheduler.service import run_source_sync
from app.scheduler.triggers import parse_schedule


def build_job_id(connector: str) -> str:
    return f"scheduler:{connector}"


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
        scheduler.add_job(
            run_source_sync,
            trigger=trigger,
            kwargs={"connector": connector, "trigger_type": "automatic"},
            id=build_job_id(connector),
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        count += 1
    return count
