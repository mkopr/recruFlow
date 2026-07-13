import logging

import httpx
import pytest
from app.db.models import IngestionFailure, Source
from app.db.session import get_engine, get_sessionmaker
from app.ingestion import registry
from app.ingestion.normalize import NOFLUFFJOBS
from app.ingestion.registry import ConnectorSpec, resolve_source_by_connector
from app.ingestion.types import IngestionResult as NoFluffJobsIngestionResult
from app.scheduler.service import ensure_sources_exist, run_source
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _enable_logger() -> None:
    logging.getLogger("app.scheduler.service").disabled = False


def _fake_spec(connector: str, dispatch: registry.Connector) -> ConnectorSpec:
    return ConnectorSpec(
        name=connector, label=registry.CONNECTOR_REGISTRY[connector].label, dispatch=dispatch
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_scheduled_run_with_zero_offers_logs_warning_and_flags_status(
    db_session: AsyncSession,
    scheduled_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _enable_logger()
    await ensure_sources_exist(db_session)
    await db_session.commit()

    async def _fake(
        session: AsyncSession, source: Source, force_refresh: bool
    ) -> NoFluffJobsIngestionResult:
        return NoFluffJobsIngestionResult(ok=True, fetched=0, created=0)

    monkeypatch.setitem(registry.CONNECTOR_REGISTRY, NOFLUFFJOBS, _fake_spec(NOFLUFFJOBS, _fake))

    with caplog.at_level(logging.WARNING, logger="app.scheduler.service"):
        record = await run_source(NOFLUFFJOBS, trigger_type="automatic")

    assert record.status == "ok"
    assert record.warning is True
    assert record.fetched == 0
    assert any(r.levelno == logging.WARNING for r in caplog.records)

    status_response = await scheduled_client.get("/scheduler/status")
    entries = {entry["connector"]: entry for entry in status_response.json()["sources"]}
    entry = entries[NOFLUFFJOBS]
    assert entry["last_run_trigger_type"] == "automatic"
    assert entry["last_run_warning"] is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_scheduled_run_first_page_failure_records_ingestion_failure(
    db_session: AsyncSession,
    scheduled_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await ensure_sources_exist(db_session)
    await db_session.commit()

    async def _fake(
        session: AsyncSession, source: Source, force_refresh: bool
    ) -> NoFluffJobsIngestionResult:
        return NoFluffJobsIngestionResult(ok=False, fetched=0, created=0, error_message="boom")

    monkeypatch.setitem(registry.CONNECTOR_REGISTRY, NOFLUFFJOBS, _fake_spec(NOFLUFFJOBS, _fake))

    record = await run_source(NOFLUFFJOBS, trigger_type="automatic")

    # scheduler_runs' existing status/warning/fetched semantics are untouched by
    # recording a dead letter alongside them (US33's acceptance criteria).
    assert record.status == "ok"
    assert record.warning is True
    assert record.fetched == 0

    engine = get_engine()
    try:
        sessionmaker = get_sessionmaker(engine)
        async with sessionmaker() as fresh_session:
            source = await resolve_source_by_connector(fresh_session, NOFLUFFJOBS)
            failure = await fresh_session.scalar(
                select(IngestionFailure).where(IngestionFailure.source_id == source.id)
            )
            assert failure is not None
            assert failure.failure_type == "run_fetch_failed"
            assert failure.error_message == "boom"
    finally:
        await engine.dispose()

    status_response = await scheduled_client.get("/scheduler/status")
    entries = {entry["connector"]: entry for entry in status_response.json()["sources"]}
    entry = entries[NOFLUFFJOBS]
    assert entry["last_run_status"] == "ok"
    assert entry["last_run_warning"] is True
    assert entry["last_run_fetched"] == 0
