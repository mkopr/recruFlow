from fastapi import APIRouter

from app.api.deps import SessionDep
from app.db.models import ScoringConfig as ScoringConfigModel
from app.db.scoring_config_repo import get_or_create_scoring_config, update_scoring_config
from app.schemas.scoring import BatchScoringResponse
from app.schemas.scoring_config import ScoringConfig
from app.scoring.batch import run_batch_scoring

router = APIRouter()


def _scoring_config_response(row: ScoringConfigModel) -> ScoringConfig:
    return ScoringConfig(
        grade_a=row.grade_a, grade_b=row.grade_b, grade_c=row.grade_c, grade_d=row.grade_d
    )


@router.post("/score/batch")
async def trigger_batch_scoring(session: SessionDep) -> BatchScoringResponse:
    summary = await run_batch_scoring(session)
    await session.commit()
    return BatchScoringResponse(
        scored=summary.scored, skipped=summary.skipped, failed=summary.failed
    )


@router.get("/scoring-config")
async def get_scoring_config(session: SessionDep) -> ScoringConfig:
    row = await get_or_create_scoring_config(session)
    await session.commit()
    return _scoring_config_response(row)


@router.put("/scoring-config")
async def put_scoring_config(payload: ScoringConfig, session: SessionDep) -> ScoringConfig:
    row = await update_scoring_config(session, payload)
    await session.commit()
    return _scoring_config_response(row)
