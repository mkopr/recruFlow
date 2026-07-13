from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IngestionFailure, ScoringFailure, Source
from app.schemas.dlq import (
    IngestionFailureListResponse,
    IngestionFailureResponse,
    ScoringFailureListResponse,
    ScoringFailureResponse,
)

# Sentinel source id: an unknown `source` filter value must yield an always-empty
# result rather than an unfiltered one, mirroring GET /offers's _NO_ACTIVE_PROFILE_ID.
_NO_MATCHING_SOURCE_ID = -1


async def _build_ingestion_filters(
    session: AsyncSession, params: Mapping[str, object]
) -> dict[str, object]:
    filters: dict[str, object] = {}
    source = params.get("source")
    if source is not None:
        resolved_id = await session.scalar(select(Source.id).where(Source.connector == source))
        filters["source_id"] = resolved_id if resolved_id is not None else _NO_MATCHING_SOURCE_ID
    return filters


async def _build_scoring_filters(
    session: AsyncSession, params: Mapping[str, object]
) -> dict[str, object]:
    filters: dict[str, object] = {}
    for key in ("offer_id", "profile_id"):
        value = params.get(key)
        if value is not None:
            filters[key] = value
    return filters


@dataclass(frozen=True)
class DeadLetterQueueSpec:
    model: type[Any]
    response_schema: type[BaseModel]
    list_response_schema: type[BaseModel]
    filterable_params: frozenset[str]
    build_filters: Callable[[AsyncSession, Mapping[str, object]], Awaitable[dict[str, object]]]

    def build_item_response(self, row: Any) -> BaseModel:
        return self.response_schema.model_validate(row)

    def build_list_response(self, rows: Sequence[Any], total: int) -> BaseModel:
        items = [self.response_schema.model_validate(row) for row in rows]
        return self.list_response_schema(items=items, total=total)


DEAD_LETTER_REGISTRY: dict[str, DeadLetterQueueSpec] = {
    "ingestion": DeadLetterQueueSpec(
        model=IngestionFailure,
        response_schema=IngestionFailureResponse,
        list_response_schema=IngestionFailureListResponse,
        filterable_params=frozenset({"source", "failure_type", "status"}),
        build_filters=_build_ingestion_filters,
    ),
    "scoring": DeadLetterQueueSpec(
        model=ScoringFailure,
        response_schema=ScoringFailureResponse,
        list_response_schema=ScoringFailureListResponse,
        filterable_params=frozenset({"offer_id", "profile_id", "failure_type", "status"}),
        build_filters=_build_scoring_filters,
    ),
}
