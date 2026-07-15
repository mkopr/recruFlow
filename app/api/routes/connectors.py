from fastapi import APIRouter
from sqlalchemy import case, func, select

from app.api.deps import SessionDep
from app.db.models import MatchScore as MatchScoreModel
from app.db.models import Offer as OfferModel
from app.db.models import Source
from app.db.profile_repo import get_active_profile
from app.ingestion.registry import CONNECTOR_REGISTRY
from app.schemas.connectors import ConnectorOption

router = APIRouter()

# Mirrors app/api/routes/offers.py's _NO_ACTIVE_PROFILE_ID: scoping the
# "is this offer scored" check to an id no MatchScore row can ever have
# yields an always-empty match set without branching the query shape.
_NO_ACTIVE_PROFILE_ID = -1


@router.get("/connectors")
async def list_connectors(session: SessionDep) -> list[ConnectorOption]:
    active_profile = await get_active_profile(session)
    active_profile_id = active_profile.id if active_profile is not None else _NO_ACTIVE_PROFILE_ID

    scored_offer_ids = select(MatchScoreModel.offer_id).where(
        MatchScoreModel.profile_id == active_profile_id
    )
    stmt = (
        select(
            Source.connector,
            func.count(OfferModel.id).label("offer_count"),
            func.count(case((OfferModel.id.in_(scored_offer_ids), OfferModel.id))).label(
                "scored_count"
            ),
        )
        .select_from(OfferModel)
        .join(Source, OfferModel.source_id == Source.id)
        .group_by(Source.connector)
    )
    rows = (await session.execute(stmt)).all()
    counts_by_connector = {
        connector: (offer_count, scored_count) for connector, offer_count, scored_count in rows
    }

    options = []
    for spec in CONNECTOR_REGISTRY.values():
        offer_count, scored_count = counts_by_connector.get(spec.name, (0, 0))
        options.append(
            ConnectorOption(
                id=spec.name,
                label=spec.label,
                offer_count=offer_count,
                scored_count=scored_count,
                unscored_count=offer_count - scored_count,
                supports_fetch_scope=spec.supports_fetch_scope,
            )
        )
    return options
