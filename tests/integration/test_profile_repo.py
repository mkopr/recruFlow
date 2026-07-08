from uuid import uuid4

import pytest
from app.db.models import MatchScore as MatchScoreModel
from app.db.models import Offer as OfferModel
from app.db.models import Profile as ProfileModel
from app.db.models import Source
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
from app.ingestion.persist import ingest_offer
from app.schemas.profile import Profile, Skill
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import reset_test_profiles

_TEST_PROFILE_NAMES = [DEFAULT_PROFILE_NAME, "profile-a", "profile-b"]


async def _reset_test_profiles(session: AsyncSession) -> None:
    await reset_test_profiles(session, _TEST_PROFILE_NAMES)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reset_test_profiles_succeeds_when_a_match_score_references_the_default_name(
    db_session: AsyncSession,
) -> None:
    """BUG15 (user stories/BUG/BUG15_...): DEFAULT_PROFILE_NAME ("active-profile") is
    not test-exclusive -- it's the same literal name upsert_active_profile assigns in
    real usage. `_reset_test_profiles`'s "deactivate all, then delete by fixed name"
    strategy assumes it always owns every profile carrying that name, but a real
    MatchScore (written by the batch-scoring job, P3US25) can reference a
    default-named profile it does not own, and the delete then raises
    ForeignKeyViolationError instead of the clean slate every test in this file
    depends on `_reset_test_profiles` to produce as its first line.
    """
    source = Source(name=f"test-source-{uuid4()}", connector=None, config_json={})
    db_session.add(source)
    await db_session.flush()

    result = await ingest_offer(
        db_session,
        {
            "source_id": source.id,
            "title": "Backend Engineer",
            "company": "Acme",
            "canonical_url": f"https://example.com/jobs/{uuid4()}",
        },
        raw_payload={},
    )
    assert result is not None
    offer_id = result[0].id

    # Reuse a profile already carrying this name if one exists (this repo's
    # long-lived dev database already has one, permanently stuck for this
    # exact reason -- see BUG15), otherwise create one, so this test reproduces
    # the bug both on a fresh database and on this contaminated one.
    existing = (
        await db_session.execute(
            select(ProfileModel).where(ProfileModel.name == DEFAULT_PROFILE_NAME)
        )
    ).scalar_one_or_none()
    if existing is not None:
        profile_id = existing.id
        created_profile = False
    else:
        profile = ProfileModel(name=DEFAULT_PROFILE_NAME, status="active", is_active=True, data={})
        db_session.add(profile)
        await db_session.flush()
        profile_id = profile.id
        created_profile = True

    db_session.add(
        MatchScoreModel(
            offer_id=offer_id,
            profile_id=profile_id,
            engine="langchain",
            score_percent=92,
            dimensions={},
            rationale="test",
        )
    )
    await db_session.commit()

    try:
        # This is exactly `_reset_test_profiles`, called as the first line of
        # nearly every test in this file and in test_profile_routes.py. It is
        # relied upon to always succeed -- it's cleanup, not the thing under
        # test -- but currently raises IntegrityError here.
        await _reset_test_profiles(db_session)

        remaining = (
            (
                await db_session.execute(
                    select(ProfileModel).where(ProfileModel.name == DEFAULT_PROFILE_NAME)
                )
            )
            .scalars()
            .all()
        )
        assert remaining == []
    finally:
        # Best-effort teardown of this test's own synthetic rows. `_reset_test_profiles`
        # above is expected to fail (that's the bug), which leaves the transaction in a
        # failed state; a rollback is needed before any further statement, and this
        # cleanup must never raise its own error over the top of the real assertion
        # failure above.
        await db_session.rollback()
        try:
            await db_session.execute(
                delete(MatchScoreModel).where(MatchScoreModel.offer_id == offer_id)
            )
            await db_session.execute(delete(OfferModel).where(OfferModel.id == offer_id))
            if created_profile:
                await db_session.execute(delete(ProfileModel).where(ProfileModel.id == profile_id))
            await db_session.execute(delete(Source).where(Source.id == source.id))
            await db_session.commit()
        except Exception:
            await db_session.rollback()


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
