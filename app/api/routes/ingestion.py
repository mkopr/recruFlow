from fastapi import APIRouter, HTTPException

from app.ingestion.service import trigger_ingest
from app.scheduler.registry import SchedulerLookupError
from app.schemas.ingestion import IngestResponse

router = APIRouter()


@router.post("/ingest/{source}")
async def trigger_ingest_route(source: str) -> IngestResponse:
    try:
        return await trigger_ingest(source)
    except SchedulerLookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
