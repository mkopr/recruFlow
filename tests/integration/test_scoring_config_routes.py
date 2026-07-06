from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from app.db.models import ScoringConfig as ScoringConfigModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _reset_scoring_config(session: AsyncSession) -> None:
    await session.execute(delete(ScoringConfigModel))
    await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_scoring_config_seeds_defaults_on_first_read(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _reset_scoring_config(db_session)

    response = await client.get("/scoring-config")

    assert response.status_code == 200
    assert response.json() == {
        "grade_a": 0.85,
        "grade_b": 0.70,
        "grade_c": 0.55,
        "grade_d": 0.40,
    }

    rows = (await db_session.execute(select(ScoringConfigModel))).scalars().all()
    assert len(rows) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_scoring_config_returns_existing_row_unchanged(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _reset_scoring_config(db_session)
    db_session.add(ScoringConfigModel(grade_a=0.9, grade_b=0.8, grade_c=0.7, grade_d=0.6))
    await db_session.commit()

    response = await client.get("/scoring-config")

    assert response.status_code == 200
    assert response.json() == {
        "grade_a": 0.9,
        "grade_b": 0.8,
        "grade_c": 0.7,
        "grade_d": 0.6,
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_put_scoring_config_persists_and_get_reflects_it(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _reset_scoring_config(db_session)

    put_response = await client.put(
        "/scoring-config",
        json={"grade_a": 0.95, "grade_b": 0.8, "grade_c": 0.65, "grade_d": 0.5},
    )
    assert put_response.status_code == 200

    get_response = await client.get("/scoring-config")

    assert get_response.json() == put_response.json()
    assert get_response.json() == {
        "grade_a": 0.95,
        "grade_b": 0.8,
        "grade_c": 0.65,
        "grade_d": 0.5,
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_put_scoring_config_rejects_non_descending_order_with_422(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _reset_scoring_config(db_session)
    db_session.add(ScoringConfigModel(grade_a=0.85, grade_b=0.70, grade_c=0.55, grade_d=0.40))
    await db_session.commit()

    response = await client.put(
        "/scoring-config",
        json={"grade_a": 0.5, "grade_b": 0.6, "grade_c": 0.3, "grade_d": 0.1},
    )

    assert response.status_code == 422

    get_response = await client.get("/scoring-config")
    assert get_response.json() == {
        "grade_a": 0.85,
        "grade_b": 0.70,
        "grade_c": 0.55,
        "grade_d": 0.40,
    }
    rows = (await db_session.execute(select(ScoringConfigModel))).scalars().all()
    assert len(rows) == 1
    assert rows[0].grade_a == 0.85


@pytest.mark.integration
@pytest.mark.asyncio
async def test_put_scoring_config_on_empty_table_creates_and_updates_in_one_call(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _reset_scoring_config(db_session)

    response = await client.put(
        "/scoring-config",
        json={"grade_a": 0.88, "grade_b": 0.77, "grade_c": 0.66, "grade_d": 0.55},
    )

    assert response.status_code == 200
    assert response.json() == {
        "grade_a": 0.88,
        "grade_b": 0.77,
        "grade_c": 0.66,
        "grade_d": 0.55,
    }
