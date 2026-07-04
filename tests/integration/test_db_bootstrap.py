import asyncio
from typing import Any

import pytest
from alembic import command
from app.db.models import Offer, Profile
from app.db.seed import _seed_offers, run_seed
from app.db.session import get_engine
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import alembic_config

V1_TABLES = {
    "sources",
    "offers",
    "profiles",
    "cv_versions",
    "match_scores",
    "applications",
}


async def _get_table_names() -> list[str]:
    engine = get_engine()
    async with engine.connect() as conn:
        names: list[str] = await conn.run_sync(lambda c: inspect(c).get_table_names())
    await engine.dispose()
    return names


@pytest.mark.integration
def test_migration_upgrade_head_creates_all_v1_tables() -> None:
    command.upgrade(alembic_config(), "head")

    table_names = asyncio.run(_get_table_names())

    assert V1_TABLES.issubset(set(table_names))


@pytest.mark.integration
def test_migration_adds_description_and_nullable_canonical_url() -> None:
    command.upgrade(alembic_config(), "head")

    async def _get_offers_columns() -> dict[str, Any]:
        engine = get_engine()
        async with engine.connect() as conn:
            columns: Any = await conn.run_sync(lambda c: inspect(c).get_columns("offers"))
        await engine.dispose()
        return {column["name"]: column for column in columns}

    columns = asyncio.run(_get_offers_columns())

    assert "description" in columns
    assert columns["description"]["nullable"] is True
    assert columns["canonical_url"]["nullable"] is True


@pytest.mark.integration
def test_migration_upgrade_head_is_idempotent() -> None:
    config = alembic_config()
    command.upgrade(config, "head")
    before = asyncio.run(_get_table_names())

    command.upgrade(config, "head")
    after = asyncio.run(_get_table_names())

    assert set(before) == set(after)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_seed_loads_sample_offers_and_creates_no_profile_rows(
    db_session: AsyncSession,
) -> None:
    profile_count_before = len((await db_session.execute(select(Profile))).scalars().all())

    await run_seed(db_session)
    await db_session.commit()

    offers = (await db_session.execute(select(Offer))).scalars().all()
    profile_count_after = len((await db_session.execute(select(Profile))).scalars().all())

    assert len(offers) >= 3
    assert profile_count_after == profile_count_before


@pytest.mark.integration
@pytest.mark.asyncio
async def test_seed_is_idempotent_on_rerun(db_session: AsyncSession) -> None:
    await run_seed(db_session)
    await db_session.commit()
    offer_count_1 = len((await db_session.execute(select(Offer))).scalars().all())

    await run_seed(db_session)
    await db_session.commit()
    offer_count_2 = len((await db_session.execute(select(Offer))).scalars().all())

    assert offer_count_1 == offer_count_2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_seed_offer_dedup_hash_conflict_is_a_noop_not_an_error(
    db_session: AsyncSession,
) -> None:
    await run_seed(db_session)
    await db_session.commit()
    source_id = (await db_session.execute(select(Offer.source_id).limit(1))).scalar_one()
    count_1 = len((await db_session.execute(select(Offer))).scalars().all())

    await _seed_offers(db_session, source_id)
    await db_session.commit()
    count_2 = len((await db_session.execute(select(Offer))).scalars().all())

    assert count_1 == count_2
