from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ScoringConfig as ScoringConfigModel
from app.schemas.scoring_config import DEFAULT_SCORING_CONFIG, ScoringConfig


async def get_or_create_scoring_config(session: AsyncSession) -> ScoringConfigModel:
    row = await session.scalar(select(ScoringConfigModel).order_by(ScoringConfigModel.id).limit(1))
    if row is None:
        row = ScoringConfigModel(**DEFAULT_SCORING_CONFIG.model_dump())
        session.add(row)
        await session.flush()
    return row


async def update_scoring_config(session: AsyncSession, config: ScoringConfig) -> ScoringConfigModel:
    row = await get_or_create_scoring_config(session)
    row.grade_a = config.grade_a
    row.grade_b = config.grade_b
    row.grade_c = config.grade_c
    row.grade_d = config.grade_d
    await session.flush()
    await session.refresh(row)
    return row
