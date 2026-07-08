from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.db.models import IngestionFailure, ScoringFailure
from app.schemas.dlq import IngestionFailureResponse, ScoringFailureResponse


@dataclass(frozen=True)
class DeadLetterQueueSpec:
    model: type[Any]
    response_schema: type[BaseModel]
    filterable_columns: frozenset[str]


DEAD_LETTER_REGISTRY: dict[str, DeadLetterQueueSpec] = {
    "ingestion": DeadLetterQueueSpec(
        model=IngestionFailure,
        response_schema=IngestionFailureResponse,
        filterable_columns=frozenset({"source_id", "failure_type", "status"}),
    ),
    "scoring": DeadLetterQueueSpec(
        model=ScoringFailure,
        response_schema=ScoringFailureResponse,
        filterable_columns=frozenset({"offer_id", "profile_id", "failure_type", "status"}),
    ),
}
