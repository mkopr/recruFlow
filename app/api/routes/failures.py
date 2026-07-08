from typing import Literal, cast

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.deps import SessionDep
from app.db.models import Source
from app.dlq.registry import DEAD_LETTER_REGISTRY, DeadLetterQueueSpec
from app.dlq.retry import perform_retry
from app.dlq.service import list_failures
from app.schemas.dlq import (
    IngestionFailureListResponse,
    IngestionFailureResponse,
    ScoringFailureListResponse,
    ScoringFailureResponse,
)

router = APIRouter()

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

# Sentinel source id: an unknown `source` filter value must yield an always-empty
# result rather than an unfiltered one, mirroring GET /offers's _NO_ACTIVE_PROFILE_ID.
_NO_MATCHING_SOURCE_ID = -1


def _spec_or_404(process: str) -> DeadLetterQueueSpec:
    spec = DEAD_LETTER_REGISTRY.get(process)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"unknown failure process: {process!r}")
    return spec


@router.get("/failures/{process}")
async def list_failures_route(
    process: str,
    session: SessionDep,
    failure_type: str | None = Query(default=None),
    source: str | None = Query(default=None, description="Connector identity (ingestion only)"),
    offer_id: int | None = Query(default=None, description="Offer id (scoring only)"),
    profile_id: int | None = Query(default=None, description="Profile id (scoring only)"),
    status: Literal["open", "resolved", "all"] = Query(default="open"),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
) -> IngestionFailureListResponse | ScoringFailureListResponse:
    spec = _spec_or_404(process)

    filters: dict[str, object] = {}
    if failure_type is not None:
        filters["failure_type"] = failure_type
    if status != "all":
        filters["status"] = status
    if process == "ingestion" and source is not None:
        resolved_id = await session.scalar(select(Source.id).where(Source.connector == source))
        filters["source_id"] = resolved_id if resolved_id is not None else _NO_MATCHING_SOURCE_ID
    if process == "scoring":
        if offer_id is not None:
            filters["offer_id"] = offer_id
        if profile_id is not None:
            filters["profile_id"] = profile_id

    rows, total = await list_failures(
        session, spec.model, limit=limit, offset=offset, filters=filters
    )
    if process == "ingestion":
        ingestion_items = [
            cast(IngestionFailureResponse, spec.response_schema.model_validate(row)) for row in rows
        ]
        return IngestionFailureListResponse(items=ingestion_items, total=total)
    scoring_items = [
        cast(ScoringFailureResponse, spec.response_schema.model_validate(row)) for row in rows
    ]
    return ScoringFailureListResponse(items=scoring_items, total=total)


@router.post("/failures/{process}/{failure_id}/retry")
async def retry_failure_route(
    process: str, failure_id: int, session: SessionDep
) -> IngestionFailureResponse | ScoringFailureResponse:
    spec = _spec_or_404(process)

    row = await session.get(spec.model, failure_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"failure {failure_id} not found")

    await perform_retry(session, row)
    if process == "ingestion":
        return cast(IngestionFailureResponse, spec.response_schema.model_validate(row))
    return cast(ScoringFailureResponse, spec.response_schema.model_validate(row))
