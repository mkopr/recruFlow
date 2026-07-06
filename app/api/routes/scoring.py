from fastapi import APIRouter

from app.api.deps import SessionDep
from app.schemas.scoring import BatchScoringResponse
from app.scoring.batch import run_batch_scoring

router = APIRouter()


@router.post("/score/batch")
async def trigger_batch_scoring(session: SessionDep) -> BatchScoringResponse:
    summary = await run_batch_scoring(session)
    await session.commit()
    return BatchScoringResponse(
        scored=summary.scored, skipped=summary.skipped, failed=summary.failed
    )
