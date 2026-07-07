from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import SessionDep
from app.db.models import Source
from app.ingestion.registry import SchedulerLookupError
from app.scheduler.runs import build_source_status, get_latest_run_by_source
from app.scheduler.service import run_source
from app.schemas.scheduler import ManualRunResponse, SchedulerStatusResponse, SourceStatus

router = APIRouter()


@router.post("/scheduler/run/{source}")
async def trigger_run(source: str) -> ManualRunResponse:
    try:
        record = await run_source(source, trigger_type="manual")
    except SchedulerLookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ManualRunResponse.model_validate(record)


@router.get("/scheduler/status")
async def scheduler_status(session: SessionDep) -> SchedulerStatusResponse:
    sources = (await session.scalars(select(Source).where(Source.connector.is_not(None)))).all()

    entries: list[SourceStatus] = []
    for source in sources:
        last_run = await get_latest_run_by_source(session, source.id)
        entries.append(build_source_status(source, last_run))

    return SchedulerStatusResponse(sources=entries)
