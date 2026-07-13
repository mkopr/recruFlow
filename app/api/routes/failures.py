from typing import Literal, cast

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import SessionDep
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

    process_params = {"source": source, "offer_id": offer_id, "profile_id": profile_id}
    provided = {key: value for key, value in process_params.items() if value is not None}
    unsupported = set(provided) - spec.filterable_params
    if unsupported:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported filter(s) for process {process!r}: {sorted(unsupported)}",
        )

    filters = await spec.build_filters(session, provided)
    if failure_type is not None:
        filters["failure_type"] = failure_type
    if status != "all":
        filters["status"] = status

    rows, total = await list_failures(
        session, spec.model, limit=limit, offset=offset, filters=filters
    )
    return cast(
        "IngestionFailureListResponse | ScoringFailureListResponse",
        spec.build_list_response(rows, total),
    )


@router.post("/failures/{process}/{failure_id}/retry")
async def retry_failure_route(
    process: str, failure_id: int, session: SessionDep
) -> IngestionFailureResponse | ScoringFailureResponse:
    spec = _spec_or_404(process)

    row = await session.get(spec.model, failure_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"failure {failure_id} not found")

    await perform_retry(session, row)
    return cast("IngestionFailureResponse | ScoringFailureResponse", spec.build_item_response(row))
