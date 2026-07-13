import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IngestionFailure, Source
from app.db.session import get_engine, get_sessionmaker
from app.dlq.service import record_failure
from app.ingestion.registry import dispatch_ingestion, resolve_source_by_connector
from app.ingestion.types import IngestionResult

logger = logging.getLogger(__name__)

BeforeDispatch = Callable[[AsyncSession, Source], Awaitable[None]]
OnSuccess = Callable[[AsyncSession, Source, IngestionResult], Awaitable[None]]
OnError = Callable[[AsyncSession, Source, Exception], Awaitable[None]]


class ConnectorDisabledError(Exception):
    """Raised when a Connector's `connector_enabled` flag is `False` (P3US37). Distinct from
    `SchedulerLookupError` (registry.py) -- that family means "this connector doesn't exist,"
    this means "it exists but is stopped" -- so callers can map the two to different HTTP
    statuses (404 vs 409) without a type check inside a shared except block.
    """


async def record_run_fetch_failure(
    session: AsyncSession,
    source: Source,
    result: IngestionResult,
    *,
    scheduler_run_id: int | None = None,
) -> None:
    """The shared `on_success` failure-recording shape every "run a connector" caller needs
    when `dispatch_ingestion` returns a failed (not raised) result (BUG37). `scheduler_run_id`
    is the only axis callers vary on -- the audited `/scheduler/run/{source}` path threads its
    `SchedulerRun.id` through, the unaudited `/ingest/{source}` path leaves it unset.
    """
    if result.ok:
        return
    fields: dict[str, Any] = {}
    if scheduler_run_id is not None:
        fields["scheduler_run_id"] = scheduler_run_id
    await record_failure(
        session,
        IngestionFailure,
        dedup_key=f"source:{source.id}",
        source_id=source.id,
        failure_type="run_fetch_failed",
        error_message=result.error_message or "ingestion failed",
        **fields,
    )


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
    callers disagree on which — nothing is committed on its behalf.

    Does not trigger batch scoring itself (BUG29): the dedicated `scoring:backlog` job
    (`app/scheduler/service.py`) already drains the unscored backlog on its own interval,
    independent of any source's ingestion schedule (BUG24). Having ingestion also trigger
    a scoring run let the two race and rescore the same offers twice.
    """
    engine = get_engine()
    try:
        sessionmaker = get_sessionmaker(engine)
        async with sessionmaker() as session:
            source = await resolve_source_by_connector(session, connector)

            if not (source.config_json or {}).get("connector_enabled", True):
                raise ConnectorDisabledError(f"connector {connector!r} is stopped")

            if before_dispatch is not None:
                await before_dispatch(session, source)
                await session.commit()

            try:
                result = await dispatch_ingestion(session, source, force_refresh=force_refresh)
            except Exception as exc:
                await on_error(session, source, exc)
                return source, None, exc

            if result.ok:
                source.last_fetched_at = datetime.now(UTC)
            if on_success is not None:
                await on_success(session, source, result)
            await session.commit()
            return source, result, None
    finally:
        await engine.dispose()
