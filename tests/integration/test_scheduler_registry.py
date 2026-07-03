from uuid import uuid4

import pytest
from app.config import get_settings
from app.connectors.justjoinit import IngestionResult as JustJoinItIngestionResult
from app.connectors.nofluffjobs import IngestionResult as NoFluffJobsIngestionResult
from app.connectors.solid_jobs import IngestionResult as SolidJobsIngestionResult
from app.db.models import Source
from app.ingestion.normalize import JUSTJOINIT, NOFLUFFJOBS, SOLID_JOBS
from app.scheduler import registry
from app.scheduler.registry import (
    DispatchResult,
    SourceNotConfiguredError,
    UnknownConnectorError,
    dispatch_ingestion,
    resolve_source_by_connector,
)
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
async def test_dispatch_ingestion_solid_jobs_passes_campaign_from_settings(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = Source(name=f"solid-jobs-{uuid4()}", connector=SOLID_JOBS, config_json={})
    db_session.add(source)
    await db_session.flush()

    captured: dict[str, str] = {}

    async def _fake_run_solid_jobs_ingestion(
        session: AsyncSession, src: Source, *, campaign: str, force_refresh: bool = False
    ) -> SolidJobsIngestionResult:
        captured["campaign"] = campaign
        return SolidJobsIngestionResult(ok=True, fetched=0, created=0)

    monkeypatch.setattr(registry, "run_solid_jobs_ingestion", _fake_run_solid_jobs_ingestion)

    result = await dispatch_ingestion(db_session, source)

    assert captured["campaign"] == get_settings().sjctl_campaign
    assert result == DispatchResult(ok=True, fetched=0, created=0)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dispatch_ingestion_justjoinit_normalizes_result_to_dispatch_result(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = Source(name=f"justjoinit-{uuid4()}", connector=JUSTJOINIT, config_json={})
    db_session.add(source)
    await db_session.flush()

    async def _fake_run_justjoinit_ingestion(
        session: AsyncSession, src: Source
    ) -> JustJoinItIngestionResult:
        return JustJoinItIngestionResult(ok=True, fetched=3, created=2)

    monkeypatch.setattr(registry, "run_justjoinit_ingestion", _fake_run_justjoinit_ingestion)

    result = await dispatch_ingestion(db_session, source)

    assert result == DispatchResult(ok=True, fetched=3, created=2)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dispatch_ingestion_nofluffjobs_normalizes_result_to_dispatch_result(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = Source(name=f"nofluffjobs-{uuid4()}", connector=NOFLUFFJOBS, config_json={})
    db_session.add(source)
    await db_session.flush()

    async def _fake_run_nofluffjobs_ingestion(
        session: AsyncSession, src: Source
    ) -> NoFluffJobsIngestionResult:
        return NoFluffJobsIngestionResult(ok=True, fetched=3, created=2)

    monkeypatch.setattr(registry, "run_nofluffjobs_ingestion", _fake_run_nofluffjobs_ingestion)

    result = await dispatch_ingestion(db_session, source)

    assert result == DispatchResult(ok=True, fetched=3, created=2)
