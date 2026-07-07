import httpx
import pytest
from app.db.models import Source
from app.db.session import get_engine, get_sessionmaker
from app.ingestion.normalize import JUSTJOINIT, NOFLUFFJOBS, SOLID_JOBS
from app.scheduler.lifecycle import build_job_id
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select


async def _get_source_schedule(connector: str) -> dict[str, object]:
    engine = get_engine()
    sessionmaker = get_sessionmaker(engine)
    async with sessionmaker() as session:
        source = await session.scalar(select(Source).where(Source.connector == connector))
        assert source is not None
        schedule: dict[str, object] = source.config_json["schedule"]
        return schedule


@pytest.mark.integration
@pytest.mark.asyncio
async def test_put_interval_persists_and_validates(scheduled_client: httpx.AsyncClient) -> None:
    reject_response = await scheduled_client.put(
        "/scheduler/sources/justjoinit/interval", json={"seconds": 30}
    )
    assert reject_response.status_code == 422

    accept_response = await scheduled_client.put(
        "/scheduler/sources/justjoinit/interval", json={"seconds": 300}
    )
    assert accept_response.status_code == 200
    assert accept_response.json()["schedule"] == {"type": "interval", "seconds": 300}

    schedule = await _get_source_schedule(JUSTJOINIT)
    assert schedule == {"type": "interval", "seconds": 300}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_put_interval_unknown_connector_returns_404(
    scheduled_client: httpx.AsyncClient,
) -> None:
    response = await scheduled_client.put(
        "/scheduler/sources/does-not-exist/interval", json={"seconds": 300}
    )
    assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cron_source_converts_to_interval(scheduled_client: httpx.AsyncClient) -> None:
    response = await scheduled_client.put(
        "/scheduler/sources/nofluffjobs/interval", json={"seconds": 900}
    )
    assert response.status_code == 200
    assert response.json()["schedule"] == {"type": "interval", "seconds": 900}

    status_response = await scheduled_client.get("/scheduler/status")
    entries = {entry["connector"]: entry for entry in status_response.json()["sources"]}
    assert entries[NOFLUFFJOBS]["schedule"] == {"type": "interval", "seconds": 900}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_put_interval_reschedules_live_job_without_restart(
    scheduled_client: httpx.AsyncClient,
) -> None:
    response = await scheduled_client.put(
        "/scheduler/sources/justjoinit/interval", json={"seconds": 111}
    )
    assert response.status_code == 200

    from app.main import app

    job = app.state.scheduler.get_job(build_job_id(JUSTJOINIT))
    assert job is not None
    assert isinstance(job.trigger, IntervalTrigger)
    assert job.trigger.interval.total_seconds() == 111


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bulk_interval_updates_every_connector(scheduled_client: httpx.AsyncClient) -> None:
    response = await scheduled_client.put("/scheduler/sources/interval", json={"seconds": 300})
    assert response.status_code == 200

    entries = {entry["connector"]: entry for entry in response.json()["sources"]}
    for connector in (SOLID_JOBS, JUSTJOINIT, NOFLUFFJOBS):
        assert entries[connector]["schedule"] == {"type": "interval", "seconds": 300}

    from app.main import app

    for connector in (SOLID_JOBS, JUSTJOINIT, NOFLUFFJOBS):
        job = app.state.scheduler.get_job(build_job_id(connector))
        assert job is not None
        assert isinstance(job.trigger, IntervalTrigger)
        assert job.trigger.interval.total_seconds() == 300


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bulk_interval_rejects_seconds_below_60(scheduled_client: httpx.AsyncClient) -> None:
    before = await _get_source_schedule(SOLID_JOBS)

    response = await scheduled_client.put("/scheduler/sources/interval", json={"seconds": 10})
    assert response.status_code == 422

    after = await _get_source_schedule(SOLID_JOBS)
    assert after == before
