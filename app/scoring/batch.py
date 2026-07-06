import logging
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MatchScore as MatchScoreModel
from app.db.models import Offer as OfferModel
from app.db.models import Source
from app.db.profile_repo import get_active_profile
from app.db.scoring_config_repo import get_or_create_scoring_config
from app.llm.matcher import LANGCHAIN_SOURCES, build_grade_scale, score_offers_with_langchain
from app.schemas.scoring_config import ScoringConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BatchScoringSummary:
    scored: int
    skipped: int
    failed: int


async def _fetch_unscored_offers(
    session: AsyncSession, profile_id: int
) -> list[tuple[OfferModel, str]]:
    already_scored = select(MatchScoreModel.offer_id).where(
        MatchScoreModel.profile_id == profile_id
    )
    stmt = (
        select(OfferModel, Source.connector)
        .join(Source, OfferModel.source_id == Source.id)
        .where(Source.connector.in_(LANGCHAIN_SOURCES))
        .where(OfferModel.id.not_in(already_scored))
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
        .where(Source.connector.in_(LANGCHAIN_SOURCES))
        .where(OfferModel.id.in_(already_scored))
    )
    return (await session.execute(stmt)).scalar_one()


async def run_batch_scoring(session: AsyncSession) -> BatchScoringSummary:
    profile_row = await get_active_profile(session)
    if profile_row is None:
        logger.info("batch scoring skipped: no active profile")
        return BatchScoringSummary(scored=0, skipped=0, failed=0)

    unscored = await _fetch_unscored_offers(session, profile_row.id)
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
    results = await score_offers_with_langchain(
        session, profile_row, unscored, grade_scale=grade_scale
    )
    failed = len(unscored) - len(results)

    logger.info(
        "batch scoring run complete: scored=%d skipped=%d failed=%d",
        len(results),
        skipped,
        failed,
    )
    return BatchScoringSummary(scored=len(results), skipped=skipped, failed=failed)
