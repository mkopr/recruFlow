from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import SessionDep
from app.db.models import Source
from app.ingestion.registry import SchedulerLookupError
from app.scheduler.runs import get_latest_run_by_source
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
        connector = source.connector
        assert connector is not None
        last_run = await get_latest_run_by_source(session, source.id)
        entries.append(
            SourceStatus(
                source_id=source.id,
                connector=connector,
                name=source.name,
                schedule=(source.config_json or {}).get("schedule", {}),
                last_fetched_at=source.last_fetched_at,
                last_run_id=last_run.id if last_run else None,
                last_run_started_at=last_run.started_at if last_run else None,
                last_run_finished_at=last_run.finished_at if last_run else None,
                last_run_status=last_run.status if last_run else None,
                last_run_trigger_type=last_run.trigger_type if last_run else None,
                last_run_fetched=last_run.fetched_count if last_run else None,
                last_run_created=last_run.created_count if last_run else None,
                last_run_warning=last_run.warning if last_run else False,
                last_run_error_message=last_run.error_message if last_run else None,
            )
        )

    return SchedulerStatusResponse(sources=entries)
