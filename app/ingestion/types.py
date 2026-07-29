from dataclasses import dataclass


@dataclass(frozen=True)
class IngestionResult:
    ok: bool
    fetched: int
    created: int
    error_message: str | None = None
    blocked_status: int | None = None
