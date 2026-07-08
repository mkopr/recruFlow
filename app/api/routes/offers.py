from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import and_, func, or_, select

from app.api.deps import SessionDep
from app.db.models import MatchScore as MatchScoreModel
from app.db.models import Offer as OfferModel
from app.db.models import Source
from app.db.profile_repo import get_active_profile
from app.schemas.match_score import MatchScoreResponse
from app.schemas.offer import OfferDetail, OfferEdit, OfferListResponse, OfferSummary

router = APIRouter()

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

# Sentinel profile id: no offer can have a MatchScore against it, so scoping the
# "latest score per offer" subquery to this id when there's no active profile
# yields an always-empty join without branching the query shape.
_NO_ACTIVE_PROFILE_ID = -1


def _offer_summary(
    offer: OfferModel, source: str, score_percent: int | None = None
) -> OfferSummary:
    return OfferSummary(
        id=offer.id,
        source=source,
        external_id=offer.external_id,
        canonical_url=offer.canonical_url,
        title=offer.title,
        company=offer.company,
        location=offer.location,
        remote=offer.remote,
        seniority=offer.seniority,
        salary_min=offer.salary_min,
        salary_max=offer.salary_max,
        salary_currency=offer.salary_currency,
        contract_type=offer.contract_type,
        posted_at=offer.posted_at,
        industry_tags=offer.industry_tags or [],
        created_at=offer.created_at,
        applied=offer.applied,
        hide=offer.hide,
        notes=offer.notes,
        score_percent=score_percent,
    )


def _offer_detail(offer: OfferModel, source: str, score_percent: int | None = None) -> OfferDetail:
    return OfferDetail(
        **_offer_summary(offer, source, score_percent).model_dump(),
        description=offer.description,
        raw_payload=offer.raw_payload,
        updated_at=offer.updated_at,
    )


def _match_score_response(row: MatchScoreModel) -> MatchScoreResponse:
    return MatchScoreResponse(
        id=row.id,
        offer_id=row.offer_id,
        profile_id=row.profile_id,
        engine=row.engine,
        score_percent=row.score_percent,
        dimensions=row.dimensions,
        rationale=row.rationale,
        created_at=row.created_at,
    )


@router.get("/offers")
async def list_offers(
    session: SessionDep,
    source: str | None = Query(
        default=None,
        description="Connector identity to filter by, e.g. justjoinit, solid_jobs, nofluffjobs",
    ),
    remote: bool | None = Query(default=None),
    seniority: str | None = Query(
        default=None,
        description=(
            "Canonical seniority level to filter by (junior/mid/senior/lead/expert); "
            "matches if the offer's seniority contains this value"
        ),
    ),
    min_salary: int | None = Query(
        default=None,
        ge=0,
        description="Minimum salary (PLN, monthly gross) an offer's range must meet or exceed",
    ),
    min_score: int | None = Query(
        default=None,
        ge=0,
        le=100,
        description=(
            "Minimum acceptable match score percentage for the active profile; keeps offers "
            "scored at least this well (unscored offers are excluded whenever this is set)"
        ),
    ),
    applied: bool | None = Query(default=None),
    show_hidden: bool = Query(default=False),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
) -> OfferListResponse:
    active_profile = await get_active_profile(session)
    active_profile_id = active_profile.id if active_profile is not None else _NO_ACTIVE_PROFILE_ID

    ranked_scores = (
        select(
            MatchScoreModel.offer_id,
            MatchScoreModel.score_percent,
            func.row_number()
            .over(
                partition_by=MatchScoreModel.offer_id,
                order_by=MatchScoreModel.created_at.desc(),
            )
            .label("rn"),
        )
        .where(MatchScoreModel.profile_id == active_profile_id)
        .subquery()
    )
    latest_score = (
        select(ranked_scores.c.offer_id, ranked_scores.c.score_percent)
        .where(ranked_scores.c.rn == 1)
        .subquery()
    )

    stmt = (
        select(OfferModel, Source.connector, Source.name, latest_score.c.score_percent)
        .join(Source, OfferModel.source_id == Source.id)
        .outerjoin(latest_score, latest_score.c.offer_id == OfferModel.id)
    )

    if source is not None:
        stmt = stmt.where(Source.connector == source)
    if remote is not None:
        stmt = stmt.where(OfferModel.remote == remote)
    if seniority is not None:
        stmt = stmt.where(OfferModel.seniority.ilike(f"%{seniority}%"))
    if min_salary is not None:
        stmt = stmt.where(
            or_(
                OfferModel.salary_max >= min_salary,
                and_(OfferModel.salary_max.is_(None), OfferModel.salary_min >= min_salary),
            )
        )
    if min_score is not None:
        stmt = stmt.where(latest_score.c.score_percent >= min_score)
    if applied is not None:
        stmt = stmt.where(OfferModel.applied == applied)
    if not show_hidden:
        stmt = stmt.where(OfferModel.hide.is_(False))

    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()

    page_stmt = (
        stmt.order_by(
            OfferModel.posted_at.desc().nulls_last(),
            OfferModel.created_at.desc(),
            OfferModel.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    )

    rows = (await session.execute(page_stmt)).all()
    items = [
        _offer_summary(offer, connector or name, offer_score_percent)
        for offer, connector, name, offer_score_percent in rows
    ]
    return OfferListResponse(items=items, total=total)


@router.get("/offers/{offer_id}")
async def get_offer(offer_id: int, session: SessionDep) -> OfferDetail:
    stmt = (
        select(OfferModel, Source.connector, Source.name)
        .join(Source, OfferModel.source_id == Source.id)
        .where(OfferModel.id == offer_id)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"offer {offer_id} not found")

    offer, connector, name = row
    return _offer_detail(offer, connector or name)


@router.patch("/offers/{offer_id}")
async def patch_offer(offer_id: int, payload: OfferEdit, session: SessionDep) -> OfferSummary:
    offer = await session.get(OfferModel, offer_id)
    if offer is None:
        raise HTTPException(status_code=404, detail=f"offer {offer_id} not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(offer, field, value)
    await session.commit()
    await session.refresh(offer)

    source = await session.get(Source, offer.source_id)
    assert source is not None

    active_profile = await get_active_profile(session)
    score_percent = None
    if active_profile is not None:
        score_percent = await session.scalar(
            select(MatchScoreModel.score_percent)
            .where(
                MatchScoreModel.offer_id == offer.id,
                MatchScoreModel.profile_id == active_profile.id,
            )
            .order_by(MatchScoreModel.created_at.desc())
            .limit(1)
        )

    return _offer_summary(offer, source.connector or source.name, score_percent)


@router.get("/offers/{offer_id}/score")
async def get_offer_score(offer_id: int, session: SessionDep) -> MatchScoreResponse | None:
    offer = await session.get(OfferModel, offer_id)
    if offer is None:
        raise HTTPException(status_code=404, detail=f"offer {offer_id} not found")

    active_profile = await get_active_profile(session)
    if active_profile is None:
        return None

    stmt = (
        select(MatchScoreModel)
        .where(
            MatchScoreModel.offer_id == offer_id,
            MatchScoreModel.profile_id == active_profile.id,
        )
        .order_by(MatchScoreModel.created_at.desc())
        .limit(1)
    )
    row = await session.scalar(stmt)
    if row is None:
        return None
    return _match_score_response(row)
