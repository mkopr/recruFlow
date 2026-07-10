from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.db.models import Source
from app.ingestion.normalize import JUSTJOINIT, NOFLUFFJOBS, SOLID_JOBS
from app.scheduler import service as service_module
from app.scheduler.service import DEFAULT_SOURCE_CONFIGS, ensure_sources_exist
from sqlalchemy import delete, select
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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ensure_sources_exist_seeds_default_fetch_range_and_auto_fetch_enabled(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The three real built-in connectors may already have been seeded by an earlier test run
    # against this persistent db_test instance -- `on_conflict_do_nothing` means re-running
    # `ensure_sources_exist` against them would never exercise a fresh insert. A throwaway
    # connector name guarantees this test observes the actual insert path.
    fresh_connector = f"fresh-{uuid4()}"
    monkeypatch.setattr(
        service_module,
        "DEFAULT_SOURCE_CONFIGS",
        {
            fresh_connector: {
                "schedule": {"type": "interval", "seconds": 300},
                "auto_fetch_enabled": True,
            }
        },
    )

    try:
        await ensure_sources_exist(db_session)
        await db_session.commit()

        source = await db_session.scalar(select(Source).where(Source.connector == fresh_connector))
        assert source is not None
        fetch_range = source.config_json["fetch_range"]
        assert fetch_range["mode"] == "range"
        assert fetch_range["until"] is None
        since = datetime.fromisoformat(fetch_range["since"])
        expected_since = datetime.now(UTC) - timedelta(days=7)
        assert abs(since - expected_since) < timedelta(seconds=30)
        assert source.config_json["auto_fetch_enabled"] is True
    finally:
        await db_session.execute(delete(Source).where(Source.connector == fresh_connector))
        await db_session.commit()
