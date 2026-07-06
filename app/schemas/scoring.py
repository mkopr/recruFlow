from pydantic import BaseModel


class BatchScoringResponse(BaseModel):
    scored: int
    skipped: int
    failed: int
