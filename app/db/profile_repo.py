from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Profile as ProfileModel
from app.schemas.profile import Profile

DEFAULT_PROFILE_NAME = "active-profile"


async def get_active_profile(session: AsyncSession) -> ProfileModel | None:
    row: ProfileModel | None = await session.scalar(
        select(ProfileModel).where(ProfileModel.is_active.is_(True))
    )
    return row


async def activate_profile(session: AsyncSession, profile_id: int) -> None:
    await session.execute(
        update(ProfileModel).where(ProfileModel.id != profile_id).values(is_active=False)
    )
    await session.execute(
        update(ProfileModel).where(ProfileModel.id == profile_id).values(is_active=True)
    )


async def upsert_active_profile(session: AsyncSession, profile: Profile) -> ProfileModel:
    row = await get_active_profile(session)
    if row is None:
        row = ProfileModel(name=DEFAULT_PROFILE_NAME, status="active", is_active=False, data={})
        session.add(row)
        await session.flush()

    row.data = profile.model_dump(mode="json")
    row.status = "active"
    await session.flush()
    await activate_profile(session, row.id)
    await session.refresh(row)
    return row
