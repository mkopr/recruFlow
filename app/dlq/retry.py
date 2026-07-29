from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.http import BlockedFetchError
from app.db.models import IngestionFailure, ScoringFailure, Source
from app.db.models import MatchScore as MatchScoreModel
from app.db.models import Offer as OfferModel
from app.db.models import Profile as ProfileModel
from app.dlq.types import FailureType
from app.ingestion.persist import persist_offer
from app.ingestion.registry import CONNECTOR_REGISTRY
from app.ingestion.service import trigger_ingest
from app.llm.matcher import MatcherError, score_offer_with_langchain
from app.schemas.offer import Offer
from app.schemas.profile import Profile

RetryHandler = Callable[[AsyncSession, Any], Awaitable[bool]]


class UnknownFailureTypeError(LookupError):
    """Raised when a dead letter row's `failure_type` doesn't match any `FailureType`
    member -- e.g. stale data from before a type was renamed, or a row written
    directly against the DB rather than through `record_failure`. Replaces a bare
    `KeyError` so this failure mode is named and easy to catch, rather than looking like
    an accidental dict typo at the call site.
    """

    def __init__(self, failure_type: str) -> None:
        super().__init__(f"no retry handler registered for failure_type={failure_type!r}")
        self.failure_type = failure_type


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


async def _retry_detail_fetch_blocked(session: AsyncSession, row: IngestionFailure) -> bool:
    """Re-fetches and persists exactly the one posting URL this row was recorded for --
    the finer, per-URL retry granularity `_retry_fetch_failed` can't offer (re-running a whole
    sitemap-cursor connector would re-walk, and re-skip, offers the cursor has already passed).
    Dispatches through the connector's own `detail_retry` hook (`ConnectorSpec.detail_retry`,
    only set for Bulldogjob/Rocket Jobs/Pracuj.pl -- see `app.ingestion.registry`).
    """
    source = await session.get(Source, row.source_id)
    assert source is not None and source.connector is not None
    if row.url is None:
        _mark_still_failing(row, "cannot retry: no url stored")
        return False
    spec = CONNECTOR_REGISTRY[source.connector]
    assert spec.detail_retry is not None, f"{source.connector} has no detail_retry handler"
    try:
        return await spec.detail_retry(session, source, row.url)
    except BlockedFetchError as exc:
        _mark_still_failing(row, f"still blocked: HTTP {exc.status_code}")
        return False


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
RETRY_HANDLERS: dict[FailureType, RetryHandler] = {
    FailureType.VALIDATION_FAILED: _retry_validation_failed,
    FailureType.PAGE_FETCH_FAILED: _retry_fetch_failed,
    FailureType.RUN_FETCH_FAILED: _retry_fetch_failed,
    FailureType.SCORING_FAILED: _retry_scoring_failed,
    FailureType.DETAIL_FETCH_BLOCKED: _retry_detail_fetch_blocked,
}

# Fails at import time (and in CI) if a new FailureType member is ever added without a
# matching handler here -- the closest thing to a compile-time exhaustiveness check a
# plain dict literal can get.
assert set(RETRY_HANDLERS) == set(FailureType), "RETRY_HANDLERS must cover every FailureType"


# These two never mutate `row` themselves on failure (see _retry_fetch_failed) -- a
# fresh failure lands on the same row from a *different* session via record_failure's
# upsert, so the caller must re-read it rather than trust its own possibly-stale copy.
_EXTERNALLY_RECORDED_FAILURE_TYPES = frozenset(
    {FailureType.PAGE_FETCH_FAILED, FailureType.RUN_FETCH_FAILED}
)


async def perform_retry(session: AsyncSession, row: Any) -> None:
    try:
        failure_type = FailureType(row.failure_type)
    except ValueError as exc:
        raise UnknownFailureTypeError(row.failure_type) from exc

    handler = RETRY_HANDLERS[failure_type]
    succeeded = await handler(session, row)
    if succeeded:
        row.status = "resolved"
        row.resolved_at = datetime.now(UTC)
    elif failure_type in _EXTERNALLY_RECORDED_FAILURE_TYPES:
        await session.refresh(row)
    await session.commit()


@dataclass(frozen=True)
class DetailRetrySummary:
    attempted: int
    resolved: int
    still_blocked: int
    abandoned: int


async def run_detail_retry_batch(
    session: AsyncSession, *, min_age_seconds: int, max_attempts: int
) -> DetailRetrySummary:
    """One tick of the `dlq:retry_403` scheduled job: picks up every open, sufficiently-old
    dead letter row whose failure was block-shaped (`blocked_status` set) -- regardless of
    `failure_type` -- and retries it through the ordinary `perform_retry`/`RETRY_HANDLERS`
    dispatch. This deliberately covers both the new `DETAIL_FETCH_BLOCKED` rows (dispatched to
    `_retry_detail_fetch_blocked`, re-fetching just the one URL) and any existing
    `PAGE_FETCH_FAILED`/`RUN_FETCH_FAILED` row now tagged as block-caused (dispatched to the
    existing whole-source `_retry_fetch_failed`) -- `perform_retry`'s own failure_type-keyed
    dispatch already handles that branching, so this selection query doesn't need to.

    `min_age_seconds` is the cooldown before an automatic retry is allowed to burn an attempt
    on a freshly-blocked row -- giving a handful of the source's own ordinary ingestion cycles
    a chance to pass first. A row already at `max_attempts` retries is moved straight to
    `status="abandoned"` (still visible/manually-retryable via `/failures`, just no longer
    picked up here) without spending another attempt.
    """
    cutoff = datetime.now(UTC) - timedelta(seconds=min_age_seconds)
    stmt = select(IngestionFailure).where(
        IngestionFailure.status == "open",
        IngestionFailure.blocked_status.is_not(None),
        IngestionFailure.occurred_at <= cutoff,
    )
    rows = (await session.scalars(stmt)).all()

    attempted = 0
    resolved = 0
    still_blocked = 0
    abandoned = 0
    for row in rows:
        if row.retry_count >= max_attempts:
            row.status = "abandoned"
            await session.commit()
            abandoned += 1
            continue

        row.retry_count += 1
        attempted += 1
        await perform_retry(session, row)
        if row.status == "resolved":
            resolved += 1
        else:
            still_blocked += 1

    return DetailRetrySummary(
        attempted=attempted, resolved=resolved, still_blocked=still_blocked, abandoned=abandoned
    )
