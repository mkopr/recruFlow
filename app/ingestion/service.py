import asyncio
import logging
from datetime import UTC, datetime

from app.db.session import get_engine, get_sessionmaker
from app.ingestion.registry import dispatch_ingestion, resolve_source_by_connector
from app.schemas.ingestion import IngestResponse

logger = logging.getLogger(__name__)


async def _trigger_ingest_async(source: str) -> IngestResponse:
    engine = get_engine()
    try:
        sessionmaker = get_sessionmaker(engine)
        async with sessionmaker() as session:
            src = await resolve_source_by_connector(session, source)

            try:
                result = await dispatch_ingestion(session, src, force_refresh=True)
            except Exception as exc:
                await session.rollback()
                logger.error("manual ingest for %r raised: %s", source, exc, exc_info=True)
                return IngestResponse(
                    source=source, ok=False, fetched=0, created=0, error_message=str(exc)
                )

            if result.ok:
                src.last_fetched_at = datetime.now(UTC)
            await session.commit()
            return IngestResponse(
                source=source,
                ok=result.ok,
                fetched=result.fetched,
                created=result.created,
                error_message=result.error_message,
            )
    finally:
        await engine.dispose()


def _trigger_ingest_sync(source: str) -> IngestResponse:
    return asyncio.run(_trigger_ingest_async(source))


async def trigger_ingest(source: str) -> IngestResponse:
    return await asyncio.to_thread(_trigger_ingest_sync, source)
