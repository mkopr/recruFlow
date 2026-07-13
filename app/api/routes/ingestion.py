from fastapi import APIRouter, HTTPException

from app.ingestion.lifecycle import ConnectorDisabledError
from app.ingestion.registry import SchedulerLookupError
from app.ingestion.service import trigger_ingest
from app.schemas.ingestion import IngestResponse

router = APIRouter()


@router.post("/ingest/{source}")
async def trigger_ingest_route(source: str, force_refresh: bool = False) -> IngestResponse:
    try:
        return await trigger_ingest(source, force_refresh=force_refresh)
    except ConnectorDisabledError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SchedulerLookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
