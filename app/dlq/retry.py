from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IngestionFailure, ScoringFailure, Source
from app.db.models import MatchScore as MatchScoreModel
from app.db.models import Offer as OfferModel
from app.db.models import Profile as ProfileModel
from app.ingestion.persist import persist_offer
from app.ingestion.service import trigger_ingest
from app.llm.matcher import MatcherError, score_offer_with_langchain
from app.schemas.offer import Offer
from app.schemas.profile import Profile

RetryHandler = Callable[[AsyncSession, Any], Awaitable[bool]]


def _mark_still_failing(row: Any, error_message: str) -> None:
    row.error_message = error_message
    row.occurred_at = datetime.now(UTC)


async def _retry_validation_failed(session: AsyncSession, row: IngestionFailure) -> bool:
    if row.raw_payload is None:
        _mark_still_failing(row, "cannot retry: no raw payload stored")
        return False
    try:
        offer = Offer.model_validate(row.raw_payload)
    except ValidationError as exc:
        _mark_still_failing(row, str(exc))
        return False
    await persist_offer(session, offer, row.raw_payload)
    return True


async def _retry_fetch_failed(session: AsyncSession, row: IngestionFailure) -> bool:
    source = await session.get(Source, row.source_id)
    assert source is not None and source.connector is not None
    result = await trigger_ingest(source.connector)
    return result.ok


async def _retry_scoring_failed(session: AsyncSession, row: ScoringFailure) -> bool:
    offer_row = await session.get(OfferModel, row.offer_id)
    profile_row = await session.get(ProfileModel, row.profile_id)
    if offer_row is None or profile_row is None:
        _mark_still_failing(row, "cannot retry: offer or profile no longer exists")
        return False

    offer = Offer.model_validate(offer_row, from_attributes=True)
    profile = Profile(**profile_row.data)
    try:
        score = await score_offer_with_langchain(
            offer_id=offer_row.id,
            profile_id=profile_row.id,
            profile=profile,
            offer=offer,
        )
    except MatcherError as exc:
        _mark_still_failing(row, str(exc))
        return False

    session.add(
        MatchScoreModel(
            offer_id=score.offer_id,
            profile_id=score.profile_id,
            engine=score.engine,
            score_percent=score.score_percent,
            dimensions=score.dimensions,
            rationale=score.rationale,
        )
    )
    return True


# page_fetch_failed and run_fetch_failed share a dedup_key (`source:{id}`, one row per
# source) and the same retry mechanism: re-trigger ingestion for the whole source. A
# fresh failure from that retry is recorded onto this exact row by the ordinary
# record_failure upsert (app/scheduler/service.py, app/ingestion/service.py), so this
# handler doesn't need to touch `row` itself on failure -- only the caller's
# `session.refresh(row)` after a `False` return picks that up.
RETRY_HANDLERS: dict[str, RetryHandler] = {
    "validation_failed": _retry_validation_failed,
    "page_fetch_failed": _retry_fetch_failed,
    "run_fetch_failed": _retry_fetch_failed,
    "scoring_failed": _retry_scoring_failed,
}


# These two never mutate `row` themselves on failure (see _retry_fetch_failed) -- a
# fresh failure lands on the same row from a *different* session via record_failure's
# upsert, so the caller must re-read it rather than trust its own possibly-stale copy.
_EXTERNALLY_RECORDED_FAILURE_TYPES = frozenset({"page_fetch_failed", "run_fetch_failed"})


async def perform_retry(session: AsyncSession, row: Any) -> None:
    handler = RETRY_HANDLERS[row.failure_type]
    succeeded = await handler(session, row)
    if succeeded:
        row.status = "resolved"
        row.resolved_at = datetime.now(UTC)
    elif row.failure_type in _EXTERNALLY_RECORDED_FAILURE_TYPES:
        await session.refresh(row)
    await session.commit()
