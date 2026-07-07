from datetime import datetime

from pydantic import BaseModel


class BatchScoringResponse(BaseModel):
    scored: int
    skipped: int
    failed: int
    remaining: int


class ScoringStatusResponse(BaseModel):
    running: bool
    processed: int
    total: int
    remaining_backlog: int
    started_at: datetime | None
    finished_at: datetime | None
    last_scored: int
    last_skipped: int
    last_failed: int
