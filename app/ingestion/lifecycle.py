import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Source
from app.db.session import get_engine, get_sessionmaker
from app.ingestion.registry import dispatch_ingestion, resolve_source_by_connector
from app.ingestion.types import IngestionResult
from app.scoring import batch

logger = logging.getLogger(__name__)

BeforeDispatch = Callable[[AsyncSession, Source], Awaitable[None]]
OnSuccess = Callable[[AsyncSession, Source, IngestionResult], Awaitable[None]]
OnError = Callable[[AsyncSession, Source, Exception], Awaitable[None]]


async def _trigger_batch_scoring_after_ingestion() -> None:
    engine = get_engine()
    try:
        sessionmaker = get_sessionmaker(engine)
        async with sessionmaker() as session:
            try:
                summary = await batch.run_batch_scoring(session)
                await session.commit()
                logger.info(
                    "post-ingestion batch scoring: scored=%d skipped=%d failed=%d remaining=%d",
                    summary.scored,
                    summary.skipped,
                    summary.failed,
                    summary.remaining,
                )
            except Exception:
                await session.rollback()
                logger.exception("post-ingestion batch scoring failed")
    finally:
        await engine.dispose()


async def run_with_lifecycle(
    connector: str,
    *,
    force_refresh: bool = False,
    before_dispatch: BeforeDispatch | None = None,
    on_success: OnSuccess | None = None,
    on_error: OnError,
) -> tuple[Source, IngestionResult | None, Exception | None]:
    """Own the engine/session/dispatch lifecycle shared by every "run a connector" flow.

    On success, `source.last_fetched_at` is stamped before `on_success` runs, then the
    session is committed — every "run a connector" door needs that checkpoint, so it's owned
    here rather than duplicated per caller. `on_error` owns rollback/commit itself since
    callers disagree on which — nothing is committed on its behalf. Batch scoring is
    triggered unconditionally afterwards (success or error) since it sweeps all unscored
    offers, not just ones from this run — this is the one call site every "run a connector"
    door (manual `/ingest`, manual `/scheduler/run`, and automatic APScheduler jobs) shares.
    """
    engine = get_engine()
    try:
        sessionmaker = get_sessionmaker(engine)
        async with sessionmaker() as session:
            source = await resolve_source_by_connector(session, connector)

            if before_dispatch is not None:
                await before_dispatch(session, source)
                await session.commit()

            try:
                result = await dispatch_ingestion(session, source, force_refresh=force_refresh)
            except Exception as exc:
                await on_error(session, source, exc)
                await _trigger_batch_scoring_after_ingestion()
                return source, None, exc

            if result.ok:
                source.last_fetched_at = datetime.now(UTC)
            if on_success is not None:
                await on_success(session, source, result)
            await session.commit()
            await _trigger_batch_scoring_after_ingestion()
            return source, result, None
    finally:
        await engine.dispose()
