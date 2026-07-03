from datetime import UTC, datetime

import pytest
from app.connectors.nofluffjobs import IngestionResult as NoFluffJobsIngestionResult
from app.db.models import Source
from app.ingestion.normalize import NOFLUFFJOBS
from app.scheduler import registry
from app.scheduler.service import ensure_sources_exist, run_source
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.integration
@pytest.mark.asyncio
async def test_successful_run_sets_source_last_fetched_at(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await ensure_sources_exist(db_session)
    await db_session.commit()

    before = datetime.now(UTC)

    async def _fake(session: AsyncSession, source: Source) -> NoFluffJobsIngestionResult:
        return NoFluffJobsIngestionResult(ok=True, fetched=3, created=2)

    monkeypatch.setattr(registry, "run_nofluffjobs_ingestion", _fake)

    await run_source(NOFLUFFJOBS, trigger_type="automatic")

    source = (await db_session.scalars(select(Source).where(Source.connector == NOFLUFFJOBS))).one()
    assert source.last_fetched_at is not None
    assert source.last_fetched_at >= before


@pytest.mark.integration
@pytest.mark.asyncio
async def test_failed_run_does_not_set_source_last_fetched_at(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await ensure_sources_exist(db_session)
    await db_session.commit()

    before = (
        (await db_session.scalars(select(Source).where(Source.connector == NOFLUFFJOBS)))
        .one()
        .last_fetched_at
    )

    async def _fake(session: AsyncSession, source: Source) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(registry, "run_nofluffjobs_ingestion", _fake)

    await run_source(NOFLUFFJOBS, trigger_type="automatic")

    source = (await db_session.scalars(select(Source).where(Source.connector == NOFLUFFJOBS))).one()
    assert source.last_fetched_at == before
