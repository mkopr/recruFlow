import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import MatchScore as MatchScoreModel
from app.db.models import Offer as OfferModel
from app.db.models import Source
from app.db.profile_repo import get_active_profile
from app.llm import matcher
from app.llm.matcher import MatcherChain, score_offers_with_langchain
from app.scoring.events import ScoreEvent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BatchScoringSummary:
    scored: int
    skipped: int
    failed: int
    remaining: int = 0
    score_events: tuple[ScoreEvent, ...] = ()


@dataclass
class ScoringProgress:
    """In-memory, single-process view of the current/last batch scoring run.

    A local single-user tool with one API process, so a module-level global is
    enough — no need for DB-backed job state just to answer "is scoring running
    right now" for the offer list page's progress banner.
    """

    running: bool = False
    processed: int = 0
    total: int = 0
    remaining_backlog: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_scored: int = 0
    last_skipped: int = 0
    last_failed: int = 0


_progress = ScoringProgress()


def get_scoring_progress() -> ScoringProgress:
    return _progress


async def _fetch_unscored_offers(
    session: AsyncSession, profile_id: int, *, limit: int
) -> list[tuple[OfferModel, str]]:
    already_scored = select(MatchScoreModel.offer_id).where(
        MatchScoreModel.profile_id == profile_id
    )
    stmt = (
        select(OfferModel, Source.connector)
        .join(Source, OfferModel.source_id == Source.id)
        .where(Source.connector.in_(matcher.LANGCHAIN_SOURCES))
        .where(OfferModel.id.not_in(already_scored))
        .order_by(
            OfferModel.posted_at.desc().nulls_last(),
            OfferModel.created_at.desc(),
            OfferModel.id.desc(),
        )
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [(offer, connector) for offer, connector in rows]


async def _count_already_scored(session: AsyncSession, profile_id: int) -> int:
    already_scored = select(MatchScoreModel.offer_id).where(
        MatchScoreModel.profile_id == profile_id
    )
    stmt = (
        select(func.count())
        .select_from(OfferModel)
        .join(Source, OfferModel.source_id == Source.id)
        .where(Source.connector.in_(matcher.LANGCHAIN_SOURCES))
        .where(OfferModel.id.in_(already_scored))
    )
    return (await session.execute(stmt)).scalar_one()


async def _count_unscored_offers(session: AsyncSession, profile_id: int) -> int:
    already_scored = select(MatchScoreModel.offer_id).where(
        MatchScoreModel.profile_id == profile_id
    )
    stmt = (
        select(func.count())
        .select_from(OfferModel)
        .join(Source, OfferModel.source_id == Source.id)
        .where(Source.connector.in_(matcher.LANGCHAIN_SOURCES))
        .where(OfferModel.id.not_in(already_scored))
    )
    return (await session.execute(stmt)).scalar_one()


async def count_unscored_backlog(session: AsyncSession) -> int:
    """Live count of offers not yet scored for the active profile.

    Computed on demand rather than cached from the last run, so it reflects the
    backlog immediately after a profile switch/edit -- before any run has picked
    it up.
    """
    profile_row = await get_active_profile(session)
    if profile_row is None:
        return 0
    return await _count_unscored_offers(session, profile_row.id)


async def run_batch_scoring(
    session: AsyncSession,
    *,
    limit: int | None = None,
    chain_factory: Callable[[], MatcherChain] | None = None,
) -> BatchScoringSummary:
    profile_row = await get_active_profile(session)
    if profile_row is None:
        logger.info("batch scoring skipped: no active profile")
        return BatchScoringSummary(scored=0, skipped=0, failed=0, remaining=0)

    batch_limit = limit if limit is not None else get_settings().batch_scoring_limit
    total_unscored = await _count_unscored_offers(session, profile_row.id)
    unscored = await _fetch_unscored_offers(session, profile_row.id, limit=batch_limit)
    skipped = await _count_already_scored(session, profile_row.id)

    _progress.running = True
    _progress.processed = 0
    _progress.total = len(unscored)
    _progress.started_at = datetime.now(UTC)
    _progress.finished_at = None
    try:
        if chain_factory is not None:
            results = await score_offers_with_langchain(
                session,
                profile_row,
                unscored,
                chain_factory=chain_factory,
                on_progress=_record_progress,
            )
        else:
            results = await score_offers_with_langchain(
                session,
                profile_row,
                unscored,
                on_progress=_record_progress,
            )
    finally:
        _progress.running = False
        _progress.finished_at = datetime.now(UTC)

    await session.flush()
    offer_by_id = {offer.id: offer for offer, _ in unscored}
    score_events = tuple(
        ScoreEvent(
            score_id=row.id,
            offer_id=row.offer_id,
            title=offer_by_id[row.offer_id].title,
            company=offer_by_id[row.offer_id].company,
            score_percent=row.score_percent,
        )
        for row in results
    )

    failed = len(unscored) - len(results)
    remaining = max(total_unscored - len(unscored), 0)
    _progress.last_scored = len(results)
    _progress.last_skipped = skipped
    _progress.last_failed = failed
    _progress.remaining_backlog = remaining

    logger.info(
        "batch scoring run complete: scored=%d skipped=%d failed=%d remaining=%d",
        len(results),
        skipped,
        failed,
        remaining,
    )
    return BatchScoringSummary(
        scored=len(results),
        skipped=skipped,
        failed=failed,
        remaining=remaining,
        score_events=score_events,
    )


def _record_progress(processed: int) -> None:
    _progress.processed = processed
