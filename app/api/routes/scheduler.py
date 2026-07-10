from apscheduler.triggers.interval import IntervalTrigger
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.api.deps import SessionDep
from app.db.models import Source
from app.ingestion.registry import SchedulerLookupError
from app.scheduler.lifecycle import build_job_id
from app.scheduler.runs import build_source_status, get_latest_run_by_source
from app.scheduler.service import (
    run_source,
    set_all_source_auto_fetch,
    set_all_source_fetch_ranges,
    set_all_source_intervals,
    set_source_auto_fetch,
    set_source_fetch_range,
    set_source_interval,
)
from app.schemas.scheduler import (
    AutoFetchUpdateRequest,
    FetchRangeUpdateRequest,
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


@router.put("/scheduler/sources/fetch-range")
async def update_all_source_fetch_ranges(
    payload: FetchRangeUpdateRequest, session: SessionDep
) -> SchedulerStatusResponse:
    fetch_range = payload.model_dump(mode="json")
    sources = await set_all_source_fetch_ranges(session, fetch_range)
    await session.commit()

    entries: list[SourceStatus] = []
    for source in sources:
        last_run = await get_latest_run_by_source(session, source.id)
        entries.append(build_source_status(source, last_run))
    return SchedulerStatusResponse(sources=entries)


@router.put("/scheduler/sources/{source}/fetch-range")
async def update_source_fetch_range(
    source: str, payload: FetchRangeUpdateRequest, session: SessionDep
) -> SourceStatus:
    fetch_range = payload.model_dump(mode="json")
    try:
        source_row = await set_source_fetch_range(session, source, fetch_range)
    except SchedulerLookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()

    last_run = await get_latest_run_by_source(session, source_row.id)
    return build_source_status(source_row, last_run)


@router.put("/scheduler/sources/auto-fetch")
async def update_all_source_auto_fetch(
    payload: AutoFetchUpdateRequest, request: Request, session: SessionDep
) -> SchedulerStatusResponse:
    sources = await set_all_source_auto_fetch(session, payload.enabled)
    await session.commit()

    scheduler = request.app.state.scheduler
    entries: list[SourceStatus] = []
    for source in sources:
        assert source.connector is not None
        job_id = build_job_id(source.connector)
        if payload.enabled:
            scheduler.resume_job(job_id)
        else:
            scheduler.pause_job(job_id)
        last_run = await get_latest_run_by_source(session, source.id)
        entries.append(build_source_status(source, last_run))
    return SchedulerStatusResponse(sources=entries)


@router.put("/scheduler/sources/{source}/auto-fetch")
async def update_source_auto_fetch(
    source: str, payload: AutoFetchUpdateRequest, request: Request, session: SessionDep
) -> SourceStatus:
    try:
        source_row = await set_source_auto_fetch(session, source, payload.enabled)
    except SchedulerLookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()

    scheduler = request.app.state.scheduler
    job_id = build_job_id(source)
    if payload.enabled:
        scheduler.resume_job(job_id)
    else:
        scheduler.pause_job(job_id)

    last_run = await get_latest_run_by_source(session, source_row.id)
    return build_source_status(source_row, last_run)
