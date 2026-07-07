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
from app.db.scoring_config_repo import get_or_create_scoring_config
from app.llm import matcher
from app.llm.matcher import MatcherChain, build_grade_scale, score_offers_with_langchain
from app.schemas.scoring_config import ScoringConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BatchScoringSummary:
    scored: int
    skipped: int
    failed: int
    remaining: int = 0


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
        .order_by(OfferModel.id)
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
    scoring_config_row = await get_or_create_scoring_config(session)
    grade_scale = build_grade_scale(
        ScoringConfig(
            grade_a=scoring_config_row.grade_a,
            grade_b=scoring_config_row.grade_b,
            grade_c=scoring_config_row.grade_c,
            grade_d=scoring_config_row.grade_d,
        )
    )

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
                grade_scale=grade_scale,
                chain_factory=chain_factory,
                on_progress=_record_progress,
            )
        else:
            results = await score_offers_with_langchain(
                session,
                profile_row,
                unscored,
                grade_scale=grade_scale,
                on_progress=_record_progress,
            )
    finally:
        _progress.running = False
        _progress.finished_at = datetime.now(UTC)

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
        scored=len(results), skipped=skipped, failed=failed, remaining=remaining
    )


def _record_progress(processed: int) -> None:
    _progress.processed = processed
