import pytest
from app.db.models import Profile as ProfileModel
from app.db.profile_repo import (
    DEFAULT_PROFILE_NAME,
    ProfileNotFoundError,
    activate_profile,
    create_draft_profile,
    get_active_profile,
    get_profile_by_id,
    upsert_active_profile,
    upsert_profile,
)
from app.schemas.profile import Profile, Skill
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

_TEST_PROFILE_NAMES = [DEFAULT_PROFILE_NAME, "profile-a", "profile-b"]


async def _reset_test_profiles(session: AsyncSession) -> None:
    # Deactivating (rather than deleting) every row avoids tripping the
    # match_scores_profile_id_fkey constraint on profiles owned by unrelated
    # tests; deleting only this suite's own fixed names avoids unique-name
    # collisions on rerun without touching rows this suite doesn't own.
    await session.execute(update(ProfileModel).values(is_active=False))
    await session.execute(delete(ProfileModel).where(ProfileModel.name.in_(_TEST_PROFILE_NAMES)))
    await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_active_profile_returns_none_when_none_active(
    db_session: AsyncSession,
) -> None:
    await _reset_test_profiles(db_session)

    result = await get_active_profile(db_session)

    assert result is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_upsert_active_profile_creates_first_row_when_none_exists(
    db_session: AsyncSession,
) -> None:
    await _reset_test_profiles(db_session)

    row = await upsert_active_profile(db_session, Profile(skills=[Skill(name="Python")]))
    await db_session.commit()

    matching = (
        (await db_session.execute(select(ProfileModel).where(ProfileModel.name == row.name)))
        .scalars()
        .all()
    )
    assert len(matching) == 1
    assert row.is_active is True
    assert row.name == DEFAULT_PROFILE_NAME
    assert row.data["skills"][0]["name"] == "Python"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_upsert_active_profile_updates_existing_active_row_in_place(
    db_session: AsyncSession,
) -> None:
    await _reset_test_profiles(db_session)

    first = await upsert_active_profile(db_session, Profile(skills=[Skill(name="Python")]))
    await db_session.commit()

    second = await upsert_active_profile(db_session, Profile(skills=[Skill(name="Rust")]))
    await db_session.commit()

    matching = (
        (
            await db_session.execute(
                select(ProfileModel).where(ProfileModel.name == DEFAULT_PROFILE_NAME)
            )
        )
        .scalars()
        .all()
    )
    assert len(matching) == 1
    assert second.id == first.id
    assert matching[0].data["skills"][0]["name"] == "Rust"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_activate_profile_deactivates_all_others(db_session: AsyncSession) -> None:
    await _reset_test_profiles(db_session)

    row_a = ProfileModel(name="profile-a", data={}, is_active=True)
    row_b = ProfileModel(name="profile-b", data={}, is_active=False)
    db_session.add_all([row_a, row_b])
    await db_session.flush()

    await activate_profile(db_session, row_b.id)
    await db_session.commit()

    refreshed_a = await db_session.get(ProfileModel, row_a.id)
    refreshed_b = await db_session.get(ProfileModel, row_b.id)
    assert refreshed_a is not None
    assert refreshed_b is not None
    assert refreshed_a.is_active is False
    assert refreshed_b.is_active is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_draft_profile_creates_inactive_draft_row(db_session: AsyncSession) -> None:
    row = await create_draft_profile(db_session, Profile(skills=[Skill(name="Rust")]))
    await db_session.commit()

    assert row.status == "draft"
    assert row.is_active is False
    assert row.data["skills"][0]["name"] == "Rust"
    assert row.name.startswith("draft-")

    await db_session.execute(delete(ProfileModel).where(ProfileModel.name == row.name))
    await db_session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_upsert_profile_with_explicit_id_and_activate_false_does_not_touch_active_flag(
    db_session: AsyncSession,
) -> None:
    await _reset_test_profiles(db_session)
    row_a = ProfileModel(name="profile-a", status="active", is_active=True, data={})
    row_b = ProfileModel(name="profile-b", status="draft", is_active=False, data={})
    db_session.add_all([row_a, row_b])
    await db_session.flush()
    await db_session.commit()

    updated = await upsert_profile(
        db_session, Profile(location_preference="Krakow"), profile_id=row_b.id, activate=False
    )
    await db_session.commit()

    refreshed_a = await db_session.get(ProfileModel, row_a.id)
    refreshed_b = await db_session.get(ProfileModel, row_b.id)
    assert refreshed_a is not None
    assert refreshed_b is not None
    assert updated.id == row_b.id
    assert refreshed_b.data["location_preference"] == "Krakow"
    assert refreshed_b.is_active is False
    assert refreshed_a.is_active is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_upsert_profile_with_explicit_id_and_activate_true_switches_active_row(
    db_session: AsyncSession,
) -> None:
    await _reset_test_profiles(db_session)
    row_a = ProfileModel(name="profile-a", status="active", is_active=True, data={})
    row_b = ProfileModel(name="profile-b", status="draft", is_active=False, data={})
    db_session.add_all([row_a, row_b])
    await db_session.flush()
    await db_session.commit()

    updated = await upsert_profile(
        db_session, Profile(location_preference="Krakow"), profile_id=row_b.id, activate=True
    )
    await db_session.commit()

    refreshed_a = await db_session.get(ProfileModel, row_a.id)
    refreshed_b = await db_session.get(ProfileModel, row_b.id)
    assert refreshed_a is not None
    assert refreshed_b is not None
    assert updated.id == row_b.id
    assert refreshed_b.is_active is True
    assert refreshed_b.status == "active"
    assert refreshed_a.is_active is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_upsert_profile_unknown_id_raises_profile_not_found_error(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(ProfileNotFoundError):
        await upsert_profile(db_session, Profile(), profile_id=999_999, activate=False)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_upsert_profile_repeated_unactivated_saves_reuse_same_default_row(
    db_session: AsyncSession,
) -> None:
    await _reset_test_profiles(db_session)

    first = await upsert_profile(
        db_session, Profile(location_preference="Warsaw"), profile_id=None, activate=False
    )
    await db_session.commit()
    second = await upsert_profile(
        db_session, Profile(location_preference="Krakow"), profile_id=None, activate=False
    )
    await db_session.commit()

    assert first.id == second.id
    assert second.is_active is False
    matching = (
        (
            await db_session.execute(
                select(ProfileModel).where(ProfileModel.name == DEFAULT_PROFILE_NAME)
            )
        )
        .scalars()
        .all()
    )
    assert len(matching) == 1
    assert matching[0].data["location_preference"] == "Krakow"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_profile_by_id_returns_none_for_unknown_id(db_session: AsyncSession) -> None:
    result = await get_profile_by_id(db_session, 999_999)

    assert result is None
