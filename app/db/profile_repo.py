from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MatchScore as MatchScoreModel
from app.db.models import Profile as ProfileModel
from app.schemas.profile import Profile

DEFAULT_PROFILE_NAME = "active-profile"


class ProfileNotFoundError(Exception):
    pass


async def get_active_profile(session: AsyncSession) -> ProfileModel | None:
    row: ProfileModel | None = await session.scalar(
        select(ProfileModel).where(ProfileModel.is_active.is_(True))
    )
    return row


async def get_profile_by_id(session: AsyncSession, profile_id: int) -> ProfileModel | None:
    return await session.get(ProfileModel, profile_id)


async def activate_profile(session: AsyncSession, profile_id: int) -> None:
    await session.execute(
        update(ProfileModel).where(ProfileModel.id != profile_id).values(is_active=False)
    )
    await session.execute(
        update(ProfileModel).where(ProfileModel.id == profile_id).values(is_active=True)
    )


async def invalidate_scores_for_profile(session: AsyncSession, profile_id: int) -> None:
    # Delete every MatchScore row for this profile so the next batch run treats
    # all its offers as unscored again. Cheap/explicit rather than tracking a staleness
    # timestamp: a full DELETE lets select_scoring_candidates's existing "no MatchScore
    # row exists" query do the rest, with no change needed to the scoring/batch machinery.
    await session.execute(delete(MatchScoreModel).where(MatchScoreModel.profile_id == profile_id))


async def upsert_profile(
    session: AsyncSession,
    profile: Profile,
    *,
    profile_id: int | None,
    activate: bool,
) -> ProfileModel:
    if profile_id is not None:
        row = await get_profile_by_id(session, profile_id)
        if row is None:
            raise ProfileNotFoundError(f"profile {profile_id} not found")
    else:
        row = await get_active_profile(session)
        if row is None:
            row = await session.scalar(
                select(ProfileModel).where(ProfileModel.name == DEFAULT_PROFILE_NAME)
            )
        if row is None:
            row = ProfileModel(
                name=DEFAULT_PROFILE_NAME,
                status="active" if activate else "draft",
                is_active=False,
                data={},
            )
            session.add(row)
            await session.flush()

    new_data = profile.model_dump(mode="json")
    data_changed = row.data != new_data
    row.data = new_data
    if activate:
        row.status = "active"
    await session.flush()
    if activate:
        await activate_profile(session, row.id)
    await session.refresh(row)

    # Editing the active profile's data in place must invalidate its existing
    # scores, or every already-scored offer keeps a stale MatchScore forever (batch
    # scoring only ever looks for offers with *no* MatchScore row). Skipped when nothing
    # actually changed so a no-op resave (e.g. re-clicking "Set as active") doesn't nuke
    # otherwise-still-valid scores.
    if row.is_active and data_changed:
        await invalidate_scores_for_profile(session, row.id)

    return row


async def upsert_active_profile(session: AsyncSession, profile: Profile) -> ProfileModel:
    return await upsert_profile(session, profile, profile_id=None, activate=True)


async def create_draft_profile(session: AsyncSession, profile: Profile) -> ProfileModel:
    row = ProfileModel(
        name=f"draft-{uuid4()}",
        status="draft",
        is_active=False,
        data=profile.model_dump(mode="json"),
    )
    session.add(row)
    await session.flush()
    return row
