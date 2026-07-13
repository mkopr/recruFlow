from uuid import uuid4

import pytest
from app.config import get_settings
from app.db.models import Source
from app.ingestion import registry
from app.ingestion.normalize import JUSTJOINIT, NOFLUFFJOBS, SOLID_JOBS
from app.ingestion.registry import (
    ConnectorSpec,
    SourceNotConfiguredError,
    UnknownConnectorError,
    dispatch_ingestion,
    resolve_source_by_connector,
)
from app.ingestion.types import IngestionResult
from app.scheduler.service import ensure_sources_exist
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resolve_source_by_connector_returns_matching_source(
    db_session: AsyncSession,
) -> None:
    # Reuses the real, singleton justjoinit Source row provisioned by
    # ensure_sources_exist (idempotent) rather than inserting a second row with
    # the same connector value — Source.connector has no uniqueness constraint,
    # so a duplicate would make resolve_source_by_connector's result ambiguous.
    await ensure_sources_exist(db_session)
    await db_session.commit()

    expected = await db_session.scalar(select(Source).where(Source.connector == JUSTJOINIT))
    assert expected is not None

    resolved = await resolve_source_by_connector(db_session, JUSTJOINIT)

    assert resolved.id == expected.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resolve_source_by_connector_unknown_connector_raises_unknown_connector_error(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(UnknownConnectorError):
        await resolve_source_by_connector(db_session, "not_a_real_connector")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resolve_source_by_connector_unconfigured_raises_source_not_configured_error(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A random connector key registered but with no Source row provisioned for it —
    # avoids relying on any of the three real connector strings being unprovisioned,
    # since other integration tests in this suite provision them via the real,
    # committing lifespan (app.scheduler.service.ensure_sources_exist).
    fake_connector = f"fake-connector-{uuid4()}"
    monkeypatch.setitem(
        registry.CONNECTOR_REGISTRY, fake_connector, registry.CONNECTOR_REGISTRY[JUSTJOINIT]
    )

    with pytest.raises(SourceNotConfiguredError):
        await resolve_source_by_connector(db_session, fake_connector)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_solid_jobs_registry_entry_uses_settings_campaign() -> None:
    # SOLID.Jobs's campaign is now bound into the registered ConnectorSpec's dispatch (a bound
    # SolidJobsConnector.run method) at CONNECTOR_REGISTRY construction time, not threaded
    # through dispatch_ingestion per-call — so this test inspects the real, unmonkeypatched
    # registry entry's bound instance instead of monkeypatching-and-capturing a kwarg.
    dispatch = registry.CONNECTOR_REGISTRY[SOLID_JOBS].dispatch
    connector_instance = dispatch.__self__  # type: ignore[attr-defined]

    assert connector_instance.campaign == get_settings().solid_jobs_campaign


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dispatch_ingestion_threads_force_refresh_to_justjoinit(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = Source(name=f"justjoinit-{uuid4()}", connector=JUSTJOINIT, config_json={})
    db_session.add(source)
    await db_session.flush()

    captured: dict[str, bool] = {}

    async def _fake_dispatch(
        session: AsyncSession, source: Source, force_refresh: bool
    ) -> IngestionResult:
        captured["force_refresh"] = force_refresh
        return IngestionResult(ok=True, fetched=0, created=0)

    monkeypatch.setitem(
        registry.CONNECTOR_REGISTRY,
        JUSTJOINIT,
        ConnectorSpec(name=JUSTJOINIT, label="JustJoin.it", dispatch=_fake_dispatch),
    )

    result = await dispatch_ingestion(db_session, source, force_refresh=True)

    assert captured["force_refresh"] is True
    assert result == IngestionResult(ok=True, fetched=0, created=0)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dispatch_ingestion_threads_force_refresh_to_nofluffjobs(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = Source(name=f"nofluffjobs-{uuid4()}", connector=NOFLUFFJOBS, config_json={})
    db_session.add(source)
    await db_session.flush()

    captured: dict[str, bool] = {}

    async def _fake_dispatch(
        session: AsyncSession, source: Source, force_refresh: bool
    ) -> IngestionResult:
        captured["force_refresh"] = force_refresh
        return IngestionResult(ok=True, fetched=0, created=0)

    monkeypatch.setitem(
        registry.CONNECTOR_REGISTRY,
        NOFLUFFJOBS,
        ConnectorSpec(name=NOFLUFFJOBS, label="NoFluffJobs", dispatch=_fake_dispatch),
    )

    result = await dispatch_ingestion(db_session, source, force_refresh=True)

    assert captured["force_refresh"] is True
    assert result == IngestionResult(ok=True, fetched=0, created=0)
