from pydantic import BaseModel


class IngestResponse(BaseModel):
    source: str
    ok: bool
    fetched: int
    created: int
    error_message: str | None = None
