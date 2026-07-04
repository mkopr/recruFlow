from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.api.deps import SessionDep
from app.cv.text_extraction import UnsupportedFileTypeError, extract_cv_text
from app.db.models import Profile as ProfileModel
from app.db.profile_repo import create_draft_profile, get_active_profile, upsert_active_profile
from app.llm.cv_extraction import CVExtractionError, extract_profile_from_cv_text
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


@router.post("/profile/upload")
async def upload_cv(session: SessionDep, file: Annotated[UploadFile, File()]) -> ProfileResponse:
    content = await file.read()
    try:
        cv_text = extract_cv_text(file.filename or "", content)
    except UnsupportedFileTypeError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc

    try:
        profile = await extract_profile_from_cv_text(cv_text)
    except CVExtractionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    row = await create_draft_profile(session, profile)
    await session.commit()
    return _profile_response(row)
