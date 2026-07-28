import logging
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IngestionFailure
from app.db.models import Offer as OfferModel
from app.dlq.service import record_failure
from app.dlq.types import FailureType
from app.ingestion.dedup import compute_dedup_hash, normalize_canonical_url
from app.schemas.offer import Offer

logger = logging.getLogger(__name__)


def _validation_failure_dedup_key(raw: dict[str, Any]) -> str:
    canonical_url = raw.get("canonical_url")
    if canonical_url:
        return f"validation:{normalize_canonical_url(canonical_url)}"
    return f"validation:{raw.get('source_id')}:{raw.get('title', '')}:{raw.get('company', '')}"


async def normalize_and_validate(session: AsyncSession, raw: dict[str, Any]) -> Offer | None:
    try:
        return Offer.model_validate(raw)
    except ValidationError as exc:
        logger.warning(
            "offer failed validation, skipping: canonical_url=%r title=%r error=%s",
            raw.get("canonical_url"),
            raw.get("title"),
            str(exc),
        )
        await record_failure(
            session,
            IngestionFailure,
            dedup_key=_validation_failure_dedup_key(raw),
            source_id=raw["source_id"],
            failure_type=FailureType.VALIDATION_FAILED,
            raw_payload=raw,
            error_message=str(exc),
        )
        return None


# No unique index backs this check (a standard Postgres unique index treats every NULL as
# distinct, the opposite of the NULL-safe salary equality this needs), so there is a narrow,
# accepted race window between two concurrent persist_offer calls for the same content-duplicate.
# See docs/adr/0028-content-based-duplicate-detection-is-independent-of-dedup-hash.md.
async def _find_content_duplicate(session: AsyncSession, offer: Offer) -> OfferModel | None:
    stmt = (
        select(OfferModel)
        .where(
            OfferModel.company == offer.company,
            OfferModel.title == offer.title,
            OfferModel.salary_min.is_not_distinct_from(offer.salary_min),
            OfferModel.salary_max.is_not_distinct_from(offer.salary_max),
            OfferModel.salary_currency.is_not_distinct_from(offer.salary_currency),
        )
        .limit(1)
    )
    row: OfferModel | None = await session.scalar(stmt)
    return row


async def persist_offer(
    session: AsyncSession, offer: Offer, raw_payload: dict[str, Any]
) -> tuple[OfferModel, bool]:
    content_duplicate = await _find_content_duplicate(session, offer)
    if content_duplicate is not None:
        logger.info(
            "skipping offer as content duplicate: company=%r title=%r salary=(%s, %s, %s) "
            "matches existing offer id=%d",
            offer.company,
            offer.title,
            offer.salary_min,
            offer.salary_max,
            offer.salary_currency,
            content_duplicate.id,
        )
        return content_duplicate, False

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
    offer = await normalize_and_validate(session, mapped_fields)
    if offer is None:
        return None
    return await persist_offer(session, offer, raw_payload)
