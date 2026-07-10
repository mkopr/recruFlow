from uuid import uuid4

import httpx
import pytest
from app.db.models import Source
from app.db.session import get_engine, get_sessionmaker
from app.ingestion.normalize import JUSTJOINIT, NOFLUFFJOBS, SOLID_JOBS
from app.scheduler.lifecycle import (
    SCORING_JOB_ID,
    build_job_id,
    register_jobs,
    register_scoring_job,
)
from app.scheduler.service import DEFAULT_SOURCE_CONFIGS
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import delete


@pytest.mark.integration
@pytest.mark.asyncio
async def test_lifespan_registers_one_job_per_builtin_source_with_configured_interval(
    scheduled_client: httpx.AsyncClient,
) -> None:
    from app.main import app

    scheduler = app.state.scheduler
    jobs = {job.id: job for job in scheduler.get_jobs()}

    for connector in (SOLID_JOBS, JUSTJOINIT, NOFLUFFJOBS):
        assert build_job_id(connector) in jobs

    # P3US28: all three built-in connectors now default to a uniform 300s interval.
    for connector in (SOLID_JOBS, JUSTJOINIT, NOFLUFFJOBS):
        job = jobs[build_job_id(connector)]
        expected_seconds = DEFAULT_SOURCE_CONFIGS[connector]["schedule"]["seconds"]
        assert isinstance(job.trigger, IntervalTrigger)
        assert job.trigger.interval.total_seconds() == expected_seconds

    # BUG24: the backlog-draining job must be registered independently of any
    # per-source ingestion schedule, so it keeps advancing even between fetches.
    assert SCORING_JOB_ID in jobs
    assert isinstance(jobs[SCORING_JOB_ID].trigger, IntervalTrigger)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_register_scoring_job_uses_the_configured_interval() -> None:
    scheduler = AsyncIOScheduler(timezone="UTC")

    register_scoring_job(scheduler, interval_seconds=45)

    job = scheduler.get_job(SCORING_JOB_ID)
    assert job is not None
    assert job.trigger.interval.total_seconds() == 45
    assert job.max_instances == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_lifespan_shutdown_stops_scheduler_cleanly() -> None:
    from app.main import app

    async with app.router.lifespan_context(app):
        scheduler = app.state.scheduler
        assert scheduler.running is True

    assert scheduler.running is False
    scheduler.get_jobs()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_register_jobs_excludes_sources_with_null_connector() -> None:
    engine = get_engine()
    sessionmaker = get_sessionmaker(engine)
    async with sessionmaker() as session:
        source = Source(name=f"no-connector-{uuid4()}", config_json={})
        session.add(source)
        await session.commit()
        source_id = source.id

    scheduler = AsyncIOScheduler(timezone="UTC")
    try:
        await register_jobs(scheduler, sessionmaker)
        registered_connectors = {job.kwargs["connector"] for job in scheduler.get_jobs()}
        assert None not in registered_connectors
    finally:
        async with sessionmaker() as session:
            await session.execute(delete(Source).where(Source.id == source_id))
            await session.commit()
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_register_jobs_pauses_job_for_source_with_auto_fetch_disabled() -> None:
    engine = get_engine()
    sessionmaker = get_sessionmaker(engine)
    connector = f"disabled-{uuid4()}"
    async with sessionmaker() as session:
        source = Source(
            name=connector,
            connector=connector,
            config_json={
                "schedule": {"type": "interval", "seconds": 300},
                "auto_fetch_enabled": False,
            },
        )
        session.add(source)
        await session.commit()
        source_id = source.id

    # `next_run_time` is only assigned once the scheduler is actually running (APScheduler
    # leaves it unset entirely on a not-yet-started scheduler) -- start/shutdown it here to
    # match the real app.state.scheduler this behavior is verified against elsewhere.
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.start()
    try:
        await register_jobs(scheduler, sessionmaker)
        job = scheduler.get_job(build_job_id(connector))
        assert job is not None
        assert job.next_run_time is None
    finally:
        scheduler.shutdown(wait=False)
        async with sessionmaker() as session:
            await session.execute(delete(Source).where(Source.id == source_id))
            await session.commit()
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_register_jobs_leaves_job_active_for_source_with_auto_fetch_enabled_or_key_absent() -> (  # noqa: E501
    None
):
    engine = get_engine()
    sessionmaker = get_sessionmaker(engine)
    connector_enabled = f"enabled-{uuid4()}"
    connector_absent = f"absent-{uuid4()}"
    async with sessionmaker() as session:
        enabled_source = Source(
            name=connector_enabled,
            connector=connector_enabled,
            config_json={
                "schedule": {"type": "interval", "seconds": 300},
                "auto_fetch_enabled": True,
            },
        )
        absent_source = Source(
            name=connector_absent,
            connector=connector_absent,
            config_json={"schedule": {"type": "interval", "seconds": 300}},
        )
        session.add_all([enabled_source, absent_source])
        await session.commit()
        enabled_id = enabled_source.id
        absent_id = absent_source.id

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.start()
    try:
        await register_jobs(scheduler, sessionmaker)
        for connector in (connector_enabled, connector_absent):
            job = scheduler.get_job(build_job_id(connector))
            assert job is not None
            assert job.next_run_time is not None
    finally:
        scheduler.shutdown(wait=False)
        async with sessionmaker() as session:
            await session.execute(delete(Source).where(Source.id.in_([enabled_id, absent_id])))
            await session.commit()
        await engine.dispose()
