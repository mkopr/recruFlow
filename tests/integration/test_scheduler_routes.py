import asyncio
import logging
import time
from uuid import uuid4

import httpx
import pytest
from app.connectors import justjoinit, nofluffjobs, solid_jobs
from app.db.models import Source
from app.db.session import get_engine, get_sessionmaker
from app.ingestion import registry
from app.ingestion.normalize import JUSTJOINIT, NOFLUFFJOBS, SOLID_JOBS
from app.ingestion.types import IngestionResult as JustJoinItIngestionResult
from app.ingestion.types import IngestionResult as NoFluffJobsIngestionResult
from app.ingestion.types import IngestionResult as SolidJobsIngestionResult
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession


def _enable_logger() -> None:
    logging.getLogger("app.scheduler.service").disabled = False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_source_now_returns_200_and_updates_status(
    scheduled_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake(session: AsyncSession, source: Source) -> JustJoinItIngestionResult:
        return JustJoinItIngestionResult(ok=True, fetched=2, created=1)

    monkeypatch.setattr(justjoinit, "run_justjoinit_ingestion", _fake)

    response = await scheduled_client.post("/scheduler/run/justjoinit")
    assert response.status_code == 200
    body = response.json()
    assert body["trigger_type"] == "manual"
    assert body["status"] == "ok"
    assert body["fetched"] == 2
    assert body["created"] == 1

    status_response = await scheduled_client.get("/scheduler/status")
    assert status_response.status_code == 200
    entries = {entry["connector"]: entry for entry in status_response.json()["sources"]}
    entry = entries[JUSTJOINIT]
    assert entry["last_run_fetched"] == 2
    assert entry["last_run_trigger_type"] == "manual"
    assert entry["last_run_status"] == "ok"
    assert entry["last_fetched_at"] is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_source_now_unknown_connector_returns_404(
    scheduled_client: httpx.AsyncClient,
) -> None:
    response = await scheduled_client.post("/scheduler/run/does-not-exist")
    assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_source_now_unconfigured_connector_returns_404(
    scheduled_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(
        registry.CONNECTOR_REGISTRY, "fake_connector", registry.CONNECTOR_REGISTRY[JUSTJOINIT]
    )

    response = await scheduled_client.post("/scheduler/run/fake_connector")

    assert response.status_code == 404
    assert "no configured source" in response.json()["detail"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_scheduler_status_returns_null_last_run_fields_for_never_run_source(
    scheduled_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fresh_connector = f"never-run-{uuid4()}"
    monkeypatch.setitem(
        registry.CONNECTOR_REGISTRY, fresh_connector, registry.CONNECTOR_REGISTRY[JUSTJOINIT]
    )

    engine = get_engine()
    sessionmaker = get_sessionmaker(engine)
    async with sessionmaker() as session:
        source = Source(name=fresh_connector, connector=fresh_connector, config_json={})
        session.add(source)
        await session.commit()
        source_id = source.id

    try:
        response = await scheduled_client.get("/scheduler/status")
        assert response.status_code == 200
        entries = {entry["connector"]: entry for entry in response.json()["sources"]}
        assert fresh_connector in entries
        entry = entries[fresh_connector]
        assert entry["last_run_status"] is None
        assert entry["last_run_started_at"] is None
        assert entry["last_fetched_at"] is None
    finally:
        async with sessionmaker() as session:
            await session.execute(delete(Source).where(Source.id == source_id))
            await session.commit()
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_scheduler_status_excludes_sources_with_null_connector(
    scheduled_client: httpx.AsyncClient,
) -> None:
    engine = get_engine()
    sessionmaker = get_sessionmaker(engine)
    async with sessionmaker() as session:
        source = Source(name=f"no-connector-{uuid4()}", config_json={})
        session.add(source)
        await session.commit()
        source_id = source.id
        source_name = source.name

    try:
        response = await scheduled_client.get("/scheduler/status")
        names = {entry["name"] for entry in response.json()["sources"]}
        assert source_name not in names
    finally:
        async with sessionmaker() as session:
            await session.execute(delete(Source).where(Source.id == source_id))
            await session.commit()
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_source_now_zero_result_flags_warning_in_status(
    scheduled_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _enable_logger()

    async def _fake(session: AsyncSession, source: Source) -> NoFluffJobsIngestionResult:
        return NoFluffJobsIngestionResult(ok=True, fetched=0, created=0)

    monkeypatch.setattr(nofluffjobs, "run_nofluffjobs_ingestion", _fake)

    with caplog.at_level(logging.WARNING, logger="app.scheduler.service"):
        response = await scheduled_client.post("/scheduler/run/nofluffjobs")

    assert response.status_code == 200
    body = response.json()
    assert body["warning"] is True
    assert any(
        NOFLUFFJOBS in record.getMessage() and record.levelno == logging.WARNING
        for record in caplog.records
    )

    status_response = await scheduled_client.get("/scheduler/status")
    entries = {entry["connector"]: entry for entry in status_response.json()["sources"]}
    assert entries[NOFLUFFJOBS]["last_run_warning"] is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_source_now_connector_exception_records_error_status_not_stuck_running(
    scheduled_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _raise(
        session: AsyncSession, source: Source, **kwargs: object
    ) -> SolidJobsIngestionResult:
        raise RuntimeError("boom")

    monkeypatch.setattr(solid_jobs, "run_solid_jobs_ingestion", _raise)

    response = await scheduled_client.post("/scheduler/run/solid_jobs")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert "boom" in body["error_message"]

    status_response = await scheduled_client.get("/scheduler/status")
    entries = {entry["connector"]: entry for entry in status_response.json()["sources"]}
    assert entries[SOLID_JOBS]["last_run_status"] == "error"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_health_endpoint_responds_during_scheduler_run(
    scheduled_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _slow(session: AsyncSession, source: Source) -> JustJoinItIngestionResult:
        await asyncio.sleep(1.5)
        return JustJoinItIngestionResult(ok=True, fetched=1, created=1)

    monkeypatch.setattr(justjoinit, "run_justjoinit_ingestion", _slow)

    run_task = asyncio.create_task(scheduled_client.post("/scheduler/run/justjoinit"))
    await asyncio.sleep(0.2)

    start = time.monotonic()
    health_response = await scheduled_client.get("/health")
    elapsed = time.monotonic() - start

    assert health_response.status_code == 200
    assert elapsed < 1.0

    run_response = await run_task
    assert run_response.status_code == 200
    assert run_response.json()["status"] == "ok"
