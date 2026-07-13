import asyncio
import logging
from dataclasses import asdict

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Source
from app.ingestion.lifecycle import record_run_fetch_failure, run_with_lifecycle
from app.ingestion.types import IngestionResult
from app.schemas.ingestion import IngestResponse

logger = logging.getLogger(__name__)


async def _trigger_ingest_async(source: str, *, force_refresh: bool = False) -> IngestResponse:
    async def on_success(session: AsyncSession, src: Source, result: IngestionResult) -> None:
        await record_run_fetch_failure(session, src, result)

    async def on_error(session: AsyncSession, src: Source, exc: Exception) -> None:
        await session.rollback()
        logger.error("manual ingest for %r raised: %s", source, exc, exc_info=True)

    _, result, exc = await run_with_lifecycle(
        source, force_refresh=force_refresh, on_success=on_success, on_error=on_error
    )

    if exc is not None:
        return IngestResponse(source=source, ok=False, fetched=0, created=0, error_message=str(exc))

    assert result is not None
    return IngestResponse(source=source, **asdict(result))


def _trigger_ingest_sync(source: str, *, force_refresh: bool = False) -> IngestResponse:
    return asyncio.run(_trigger_ingest_async(source, force_refresh=force_refresh))


async def trigger_ingest(source: str, *, force_refresh: bool = False) -> IngestResponse:
    return await asyncio.to_thread(_trigger_ingest_sync, source, force_refresh=force_refresh)
