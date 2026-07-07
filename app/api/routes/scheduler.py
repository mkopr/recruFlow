from apscheduler.triggers.interval import IntervalTrigger
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.api.deps import SessionDep
from app.db.models import Source
from app.ingestion.registry import SchedulerLookupError
from app.scheduler.lifecycle import build_job_id
from app.scheduler.runs import build_source_status, get_latest_run_by_source
from app.scheduler.service import run_source, set_all_source_intervals, set_source_interval
from app.schemas.scheduler import (
    IntervalUpdateRequest,
    ManualRunResponse,
    SchedulerStatusResponse,
    SourceStatus,
)

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


@router.put("/scheduler/sources/interval")
async def update_all_source_intervals(
    payload: IntervalUpdateRequest, request: Request, session: SessionDep
) -> SchedulerStatusResponse:
    sources = await set_all_source_intervals(session, payload.seconds)
    await session.commit()

    scheduler = request.app.state.scheduler
    entries: list[SourceStatus] = []
    for source in sources:
        assert source.connector is not None
        scheduler.reschedule_job(
            build_job_id(source.connector), trigger=IntervalTrigger(seconds=payload.seconds)
        )
        last_run = await get_latest_run_by_source(session, source.id)
        entries.append(build_source_status(source, last_run))
    return SchedulerStatusResponse(sources=entries)


@router.put("/scheduler/sources/{source}/interval")
async def update_source_interval(
    source: str, payload: IntervalUpdateRequest, request: Request, session: SessionDep
) -> SourceStatus:
    try:
        source_row = await set_source_interval(session, source, payload.seconds)
    except SchedulerLookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()

    scheduler = request.app.state.scheduler
    scheduler.reschedule_job(build_job_id(source), trigger=IntervalTrigger(seconds=payload.seconds))

    last_run = await get_latest_run_by_source(session, source_row.id)
    return build_source_status(source_row, last_run)
