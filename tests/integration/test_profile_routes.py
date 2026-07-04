from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from app.db.models import Profile as ProfileModel
from app.db.profile_repo import DEFAULT_PROFILE_NAME
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

_TEST_PROFILE_NAMES = [DEFAULT_PROFILE_NAME]


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _reset_test_profiles(session: AsyncSession) -> None:
    # Deactivating (rather than deleting) every row avoids tripping the
    # match_scores_profile_id_fkey constraint on profiles owned by unrelated
    # tests; deleting only this suite's own fixed name avoids unique-name
    # collisions on rerun without touching rows this suite doesn't own.
    await session.execute(update(ProfileModel).values(is_active=False))
    await session.execute(delete(ProfileModel).where(ProfileModel.name.in_(_TEST_PROFILE_NAMES)))
    await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_profile_returns_active_profile_fields(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _reset_test_profiles(db_session)
    row = ProfileModel(
        name=DEFAULT_PROFILE_NAME,
        status="active",
        is_active=True,
        data={
            "skills": [{"name": "Go", "proficiency": "senior", "years": 5}],
            "past_roles": [],
            "education": [],
            "certifications": [],
            "languages": [],
            "deal_breakers": [],
        },
    )
    db_session.add(row)
    await db_session.commit()

    response = await client.get("/profile")

    assert response.status_code == 200
    assert response.json()["profile"]["skills"][0]["name"] == "Go"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_profile_returns_null_body_when_none_active(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _reset_test_profiles(db_session)

    response = await client.get("/profile")

    assert response.status_code == 200
    assert response.json() is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_put_profile_creates_and_activates_first_profile_on_empty_db(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _reset_test_profiles(db_session)

    response = await client.put("/profile", json={"skills": [{"name": "Rust"}]})

    assert response.status_code == 200
    assert response.json()["is_active"] is True

    get_response = await client.get("/profile")
    assert get_response.json()["profile"]["skills"][0]["name"] == "Rust"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_put_profile_updates_fields_and_get_reflects_change(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _reset_test_profiles(db_session)

    await client.put("/profile", json={"location_preference": "Warsaw"})
    await client.put("/profile", json={"location_preference": "Krakow"})

    response = await client.get("/profile")
    assert response.json()["profile"]["location_preference"] == "Krakow"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_put_profile_rejects_invalid_payload_with_422(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _reset_test_profiles(db_session)

    response = await client.put("/profile", json={"skills": [{"proficiency": "expert"}]})

    assert response.status_code == 422
    rows = (
        (
            await db_session.execute(
                select(ProfileModel).where(ProfileModel.name == DEFAULT_PROFILE_NAME)
            )
        )
        .scalars()
        .all()
    )
    assert rows == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_put_profile_activating_second_profile_deactivates_first(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _reset_test_profiles(db_session)
    row_a = ProfileModel(name=DEFAULT_PROFILE_NAME, status="active", is_active=True, data={})
    db_session.add(row_a)
    await db_session.commit()

    response = await client.put("/profile", json={"location_preference": "Gdansk"})

    assert response.status_code == 200
    assert response.json()["id"] == row_a.id
    active_rows = (
        (await db_session.execute(select(ProfileModel).where(ProfileModel.is_active.is_(True))))
        .scalars()
        .all()
    )
    assert len(active_rows) == 1
    assert active_rows[0].id == row_a.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_put_profile_with_profile_id_and_activate_false_leaves_other_active_profile_unchanged(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _reset_test_profiles(db_session)
    active_row = ProfileModel(
        name=DEFAULT_PROFILE_NAME,
        status="active",
        is_active=True,
        data={"location_preference": "Warsaw"},
    )
    draft_row = ProfileModel(name="draft-under-test", status="draft", is_active=False, data={})
    db_session.add_all([active_row, draft_row])
    await db_session.commit()

    response = await client.put(
        "/profile",
        params={"profile_id": draft_row.id, "activate": "false"},
        json={"location_preference": "Krakow"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == draft_row.id
    assert body["is_active"] is False
    assert body["profile"]["location_preference"] == "Krakow"

    get_response = await client.get("/profile")
    assert get_response.json()["profile"]["location_preference"] == "Warsaw"

    await db_session.execute(delete(ProfileModel).where(ProfileModel.name == "draft-under-test"))
    await db_session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_put_profile_with_profile_id_and_activate_true_promotes_target_profile(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _reset_test_profiles(db_session)
    active_row = ProfileModel(
        name=DEFAULT_PROFILE_NAME,
        status="active",
        is_active=True,
        data={"location_preference": "Warsaw"},
    )
    draft_row = ProfileModel(name="draft-under-test", status="draft", is_active=False, data={})
    db_session.add_all([active_row, draft_row])
    await db_session.commit()

    response = await client.put(
        "/profile",
        params={"profile_id": draft_row.id, "activate": "true"},
        json={"location_preference": "Krakow"},
    )

    assert response.status_code == 200
    assert response.json()["is_active"] is True

    get_response = await client.get("/profile")
    assert get_response.json()["profile"]["location_preference"] == "Krakow"

    await db_session.execute(delete(ProfileModel).where(ProfileModel.name == "draft-under-test"))
    await db_session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_put_profile_unknown_profile_id_returns_404(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _reset_test_profiles(db_session)

    response = await client.put(
        "/profile", params={"profile_id": 999_999}, json={"location_preference": "Krakow"}
    )

    assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_put_profile_default_params_still_activate_current_behavior(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _reset_test_profiles(db_session)

    response = await client.put("/profile", json={"location_preference": "Poznan"})

    assert response.status_code == 200
    assert response.json()["is_active"] is True
