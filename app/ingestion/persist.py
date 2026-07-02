import logging
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Offer as OfferModel
from app.ingestion.dedup import compute_dedup_hash
from app.schemas.offer import Offer

logger = logging.getLogger(__name__)


def normalize_and_validate(raw: dict[str, Any]) -> Offer | None:
    try:
        return Offer.model_validate(raw)
    except ValidationError as exc:
        logger.warning(
            "offer failed validation, skipping: canonical_url=%r title=%r error=%s",
            raw.get("canonical_url"),
            raw.get("title"),
            str(exc),
        )
        return None


async def persist_offer(
    session: AsyncSession, offer: Offer, raw_payload: dict[str, Any]
) -> tuple[OfferModel, bool]:
    dedup_hash = compute_dedup_hash(offer)
    stmt = (
        pg_insert(OfferModel)
        .values(dedup_hash=dedup_hash, raw_payload=raw_payload, **offer.model_dump())
        .on_conflict_do_nothing(index_elements=[OfferModel.dedup_hash])
        .returning(OfferModel.id)
    )
    inserted_id = (await session.execute(stmt)).scalar_one_or_none()
    created = inserted_id is not None
    row = await session.scalar(select(OfferModel).where(OfferModel.dedup_hash == dedup_hash))
    assert row is not None
    return row, created


async def ingest_offer(
    session: AsyncSession, mapped_fields: dict[str, Any], raw_payload: dict[str, Any]
) -> tuple[OfferModel, bool] | None:
    offer = normalize_and_validate(mapped_fields)
    if offer is None:
        return None
    return await persist_offer(session, offer, raw_payload)
