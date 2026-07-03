from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import and_, or_, select

from app.api.deps import SessionDep
from app.db.models import MatchScore, Source
from app.db.models import Offer as OfferModel
from app.schemas.offer import OfferDetail, OfferSummary

router = APIRouter()


def _offer_summary(offer: OfferModel, source: str) -> OfferSummary:
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
        created_at=offer.created_at,
    )


def _offer_detail(offer: OfferModel, source: str) -> OfferDetail:
    return OfferDetail(
        **_offer_summary(offer, source).model_dump(),
        description=offer.description,
        raw_payload=offer.raw_payload,
        updated_at=offer.updated_at,
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
    grade: str | None = Query(
        default=None,
        min_length=1,
        max_length=1,
        description=(
            "Single-letter match grade (A-F) to filter by; "
            "matches against any recorded MatchScore for the offer"
        ),
    ),
) -> list[OfferSummary]:
    stmt = select(OfferModel, Source.connector, Source.name).join(
        Source, OfferModel.source_id == Source.id
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
    if grade is not None:
        stmt = stmt.where(
            OfferModel.id.in_(select(MatchScore.offer_id).where(MatchScore.grade == grade))
        )

    rows = (await session.execute(stmt)).all()
    return [_offer_summary(offer, connector or name) for offer, connector, name in rows]


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
