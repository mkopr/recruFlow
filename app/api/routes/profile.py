from fastapi import APIRouter

from app.api.deps import SessionDep
from app.db.models import Profile as ProfileModel
from app.db.profile_repo import get_active_profile, upsert_active_profile
from app.schemas.profile import Profile, ProfileResponse

router = APIRouter()


def _profile_response(row: ProfileModel) -> ProfileResponse:
    return ProfileResponse(
        id=row.id,
        name=row.name,
        status=row.status,
        is_active=row.is_active,
        profile=Profile(**row.data),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/profile")
async def get_profile(session: SessionDep) -> ProfileResponse | None:
    row = await get_active_profile(session)
    if row is None:
        return None
    return _profile_response(row)


@router.put("/profile")
async def put_profile(payload: Profile, session: SessionDep) -> ProfileResponse:
    row = await upsert_active_profile(session, payload)
    await session.commit()
    return _profile_response(row)
