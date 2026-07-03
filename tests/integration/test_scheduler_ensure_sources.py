import pytest
from app.db.models import Source
from app.ingestion.normalize import JUSTJOINIT, NOFLUFFJOBS, SOLID_JOBS
from app.scheduler.service import DEFAULT_SOURCE_CONFIGS, ensure_sources_exist
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ensure_sources_exist_creates_three_builtin_sources(
    db_session: AsyncSession,
) -> None:
    await ensure_sources_exist(db_session)
    await db_session.commit()

    rows = (
        (await db_session.execute(select(Source).where(Source.connector.is_not(None))))
        .scalars()
        .all()
    )
    by_connector = {row.connector: row for row in rows if row.connector is not None}

    assert set(by_connector) == {SOLID_JOBS, JUSTJOINIT, NOFLUFFJOBS}
    for connector, row in by_connector.items():
        assert (
            row.config_json["schedule"]["type"]
            == DEFAULT_SOURCE_CONFIGS[connector]["schedule"]["type"]
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ensure_sources_exist_is_idempotent_and_preserves_existing_config(
    db_session: AsyncSession,
) -> None:
    await ensure_sources_exist(db_session)
    await db_session.commit()

    source = await db_session.scalar(select(Source).where(Source.connector == SOLID_JOBS))
    assert source is not None
    original_config = dict(source.config_json)
    mutated_schedule = {"type": "interval", "seconds": 42}

    try:
        source.config_json = {**original_config, "schedule": mutated_schedule}
        await db_session.commit()

        await ensure_sources_exist(db_session)
        await db_session.commit()

        refreshed = await db_session.scalar(select(Source).where(Source.connector == SOLID_JOBS))
        assert refreshed is not None
        assert refreshed.config_json["schedule"] == mutated_schedule
    finally:
        source.config_json = original_config
        await db_session.commit()
