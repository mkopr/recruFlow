import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Source
from app.ingestion.lifecycle import run_with_lifecycle
from app.ingestion.types import IngestionResult
from app.schemas.ingestion import IngestResponse

logger = logging.getLogger(__name__)


async def _trigger_ingest_async(source: str) -> IngestResponse:
    async def on_success(session: AsyncSession, src: Source, result: IngestionResult) -> None:
        if result.ok:
            src.last_fetched_at = datetime.now(UTC)

    async def on_error(session: AsyncSession, src: Source, exc: Exception) -> None:
        await session.rollback()
        logger.error("manual ingest for %r raised: %s", source, exc, exc_info=True)

    _, result, exc = await run_with_lifecycle(
        source, force_refresh=True, on_success=on_success, on_error=on_error
    )

    if exc is not None:
        return IngestResponse(source=source, ok=False, fetched=0, created=0, error_message=str(exc))

    assert result is not None
    return IngestResponse(
        source=source,
        ok=result.ok,
        fetched=result.fetched,
        created=result.created,
        error_message=result.error_message,
    )


def _trigger_ingest_sync(source: str) -> IngestResponse:
    return asyncio.run(_trigger_ingest_async(source))


async def trigger_ingest(source: str) -> IngestResponse:
    return await asyncio.to_thread(_trigger_ingest_sync, source)
