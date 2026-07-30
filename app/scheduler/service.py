import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.connectors.proxy_pool import get_shared_proxy_pool
from app.db.models import SchedulerRun, Source
from app.db.session import get_engine, get_sessionmaker
from app.dlq import retry as dlq_retry
from app.ingestion.lifecycle import record_run_fetch_failure, run_with_lifecycle
from app.ingestion.registry import CONNECTOR_REGISTRY, resolve_source_by_connector
from app.ingestion.types import IngestionResult
from app.scheduler.runs import finish_run_error, finish_run_ok, start_run
from app.scoring import batch
from app.scoring.events import publish_score

logger = logging.getLogger(__name__)


def _default_config_template() -> dict[str, Any]:
    """The one config shape every registered Connector is seeded with (see
    `docs/adr/0022-connector-registry-is-the-single-source-of-truth.md`) -- replaces the
    three near-duplicated `DEFAULT_SOURCE_CONFIGS` entries this used to be. No per-connector
    overrides exist today; a future connector needing a different default schedule would add
    one after seeding, the same way `_default_fetch_range` is layered on in `ensure_sources_exist`.
    """
    return {
        "schedule": {"type": "interval", "seconds": 300},
        "auto_fetch_enabled": True,
        "connector_enabled": True,
        "fetch_scope": {"mode": "all"},
    }


def _default_fetch_range() -> dict[str, Any]:
    """Computed fresh per call (not baked into `DEFAULT_SOURCE_CONFIGS`, a module-level
    constant evaluated once at import time) so "seed time minus 7 days" reflects the
    actual moment a source is first inserted, not process start.
    """
    return {
        "mode": "range",
        "since": (datetime.now(UTC) - timedelta(days=7)).isoformat(),
        "until": None,
    }


async def ensure_sources_exist(session: AsyncSession) -> None:
    for connector in CONNECTOR_REGISTRY:
        stmt = (
            pg_insert(Source)
            .values(
                name=connector,
                connector=connector,
                config_json={
                    **_default_config_template(),
                    "fetch_range": _default_fetch_range(),
                    **CONNECTOR_REGISTRY[connector].seed_config_overrides,
                },
            )
            .on_conflict_do_nothing(index_elements=[Source.name])
        )
        await session.execute(stmt)


@dataclass(frozen=True)
class SchedulerRunRecord:
    id: int
    source_id: int
    connector: str
    trigger_type: str
    status: str
    fetched: int | None
    created: int | None
    warning: bool
    error_message: str | None
    started_at: datetime
    finished_at: datetime | None


async def _run_source_async(connector: str, *, trigger_type: str) -> SchedulerRunRecord:
    run: SchedulerRun | None = None

    async def before_dispatch(session: AsyncSession, source: Source) -> None:
        nonlocal run
        run = await start_run(session, source.id, trigger_type=trigger_type)

    async def on_success(session: AsyncSession, source: Source, result: IngestionResult) -> None:
        assert run is not None
        warning = result.fetched == 0
        await record_run_fetch_failure(session, source, result, scheduler_run_id=run.id)
        await finish_run_ok(
            session, run, fetched=result.fetched, created=result.created, warning=warning
        )
        if warning:
            logger.warning(
                "connector %r returned zero results on this run, possible source breakage",
                connector,
            )

    async def on_error(session: AsyncSession, source: Source, exc: Exception) -> None:
        assert run is not None
        await finish_run_error(session, run, error_message=str(exc))
        await session.commit()

    await run_with_lifecycle(
        connector, before_dispatch=before_dispatch, on_success=on_success, on_error=on_error
    )

    assert run is not None
    return SchedulerRunRecord(
        id=run.id,
        source_id=run.source_id,
        connector=connector,
        trigger_type=run.trigger_type,
        status=run.status,
        fetched=run.fetched_count,
        created=run.created_count,
        warning=run.warning,
        error_message=run.error_message,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def run_source_sync(connector: str, *, trigger_type: str) -> SchedulerRunRecord:
    return asyncio.run(_run_source_async(connector, trigger_type=trigger_type))


async def run_source(connector: str, *, trigger_type: str) -> SchedulerRunRecord:
    return await asyncio.to_thread(run_source_sync, connector, trigger_type=trigger_type)


async def run_scoring_job() -> batch.BatchScoringSummary:
    """One tick of the dedicated backlog-draining job (own engine/session, like
    `_run_source_async`). Runs on a fixed interval independent of any source's own
    ingestion cadence, so the active profile's backlog keeps draining even when no
    connector happens to fire.

    Registered directly as a coroutine function with `AsyncIOScheduler` (unlike
    `run_source_sync`/`run_source`'s sync-wrapper-plus-thread-pool pattern for ingestion,
    which some connectors' synchronous HTTP calls genuinely need) so it runs on the
    scheduler's own event loop -- the same loop the rest of the app runs on -- rather than
    in a fresh event loop via `asyncio.run()` inside a worker thread. `app/scoring/batch.py`'s
    `_scoring_lock` is a plain `asyncio.Lock`, which binds to whichever event loop first
    acquires it; running this job on a second, throwaway loop per tick made that lock
    (correctly shared with the `POST /score/batch` route's own call, on the app's main loop)
    raise "bound to a different event loop" the moment both paths had ever touched it.
    """
    engine = get_engine()
    try:
        sessionmaker = get_sessionmaker(engine)
        async with sessionmaker() as session:
            try:
                summary = await batch.run_batch_scoring(session)
                await session.commit()
                for event in summary.score_events:
                    publish_score(event)
                logger.info(
                    "scheduled backlog scoring: scored=%d skipped=%d failed=%d remaining=%d",
                    summary.scored,
                    summary.skipped,
                    summary.failed,
                    summary.remaining,
                )
                return summary
            except Exception:
                await session.rollback()
                logger.exception("scheduled backlog scoring failed")
                raise
    finally:
        await engine.dispose()


async def run_detail_retry_job() -> dlq_retry.DetailRetrySummary:
    """One tick of the dedicated `dlq:retry_403` job (own engine/session, like
    `run_scoring_job`/`_run_source_async`). Runs on a fixed interval independent of any
    source's own ingestion cadence -- per BUG43, a fresh context/IP is what clears a
    Cloudflare-style block, not elapsed time within the same run, so retrying belongs in its
    own decoupled job rather than inline at the end of a connector's `run()`.
    """
    settings = get_settings()
    engine = get_engine()
    try:
        sessionmaker = get_sessionmaker(engine)
        async with sessionmaker() as session:
            try:
                # `run_detail_retry_batch` commits per-row internally (via `perform_retry`),
                # so there's no batch-level commit needed here, unlike `run_scoring_job`.
                summary = await dlq_retry.run_detail_retry_batch(
                    session,
                    min_age_seconds=settings.detail_retry_min_age_seconds,
                    max_attempts=settings.detail_retry_max_attempts,
                )
                logger.info(
                    "scheduled 403/429 retry: attempted=%d resolved=%d still_blocked=%d "
                    "abandoned=%d",
                    summary.attempted,
                    summary.resolved,
                    summary.still_blocked,
                    summary.abandoned,
                )
                return summary
            except Exception:
                logger.exception("scheduled 403/429 retry failed")
                raise
    finally:
        await engine.dispose()


def run_proxy_pool_topup_job() -> int:
    """One tick of the proxy pool top-up job. Unlike `run_scoring_job`/`run_detail_retry_job`
    (registered as coroutine functions so they run on the scheduler's own event loop, since
    neither has any blocking call of its own), this is a plain sync function -- mirroring
    `run_source_sync`'s shape -- because `ProxyPool.top_up` makes genuinely blocking HTTP
    calls (`FreeProxy(...).get()`) that would otherwise freeze the whole API's event loop
    for the duration of a scrape-and-verify pass, the same class of bug BUG42 found and fixed
    for connectors' own synchronous fetches. `AsyncIOScheduler` runs a plain (non-coroutine)
    job function in its default thread-pool executor, off the main loop, which is exactly
    what a blocking call like this needs. No DB session/engine is needed here, unlike
    `run_scoring_job`/`run_detail_retry_job` -- the pool is pure in-memory state.
    """
    settings = get_settings()
    pool = get_shared_proxy_pool()
    admitted = pool.top_up(logger, max_attempts=settings.proxy_pool_target_size * 4)
    logger.info("scheduled proxy pool top-up: admitted=%d pool_size=%d", admitted, pool.size())
    return admitted


async def set_source_interval(session: AsyncSession, connector: str, seconds: int) -> Source:
    source = await resolve_source_by_connector(session, connector)
    source.config_json = {
        **source.config_json,
        "schedule": {"type": "interval", "seconds": seconds},
    }
    await session.flush()
    return source


async def set_all_source_intervals(session: AsyncSession, seconds: int) -> list[Source]:
    sources = (await session.scalars(select(Source).where(Source.connector.is_not(None)))).all()
    for source in sources:
        source.config_json = {
            **source.config_json,
            "schedule": {"type": "interval", "seconds": seconds},
        }
        await session.flush()
    return list(sources)


async def set_source_fetch_range(
    session: AsyncSession, connector: str, fetch_range: dict[str, Any]
) -> Source:
    source = await resolve_source_by_connector(session, connector)
    source.config_json = {**source.config_json, "fetch_range": fetch_range}
    await session.flush()
    return source


async def set_all_source_fetch_ranges(
    session: AsyncSession, fetch_range: dict[str, Any]
) -> list[Source]:
    sources = (await session.scalars(select(Source).where(Source.connector.is_not(None)))).all()
    for source in sources:
        source.config_json = {**source.config_json, "fetch_range": fetch_range}
        await session.flush()
    return list(sources)


class FetchScopeNotSupportedError(Exception):
    pass


async def set_source_fetch_scope(
    session: AsyncSession, connector: str, fetch_scope: dict[str, Any]
) -> Source:
    source = await resolve_source_by_connector(session, connector)
    if (
        fetch_scope.get("mode") == "filtered"
        and not CONNECTOR_REGISTRY[connector].supports_fetch_scope
    ):
        raise FetchScopeNotSupportedError(
            f"connector {connector!r} does not support filtered fetch scope"
        )
    source.config_json = {**source.config_json, "fetch_scope": fetch_scope}
    await session.flush()
    return source


async def set_source_auto_fetch(session: AsyncSession, connector: str, enabled: bool) -> Source:
    source = await resolve_source_by_connector(session, connector)
    source.config_json = {**source.config_json, "auto_fetch_enabled": enabled}
    await session.flush()
    return source


async def set_all_source_auto_fetch(session: AsyncSession, enabled: bool) -> list[Source]:
    sources = (await session.scalars(select(Source).where(Source.connector.is_not(None)))).all()
    for source in sources:
        source.config_json = {**source.config_json, "auto_fetch_enabled": enabled}
        await session.flush()
    return list(sources)


async def set_source_enabled(session: AsyncSession, connector: str, enabled: bool) -> Source:
    source = await resolve_source_by_connector(session, connector)
    source.config_json = {**source.config_json, "connector_enabled": enabled}
    await session.flush()
    return source


async def set_all_source_enabled(session: AsyncSession, enabled: bool) -> list[Source]:
    sources = (await session.scalars(select(Source).where(Source.connector.is_not(None)))).all()
    for source in sources:
        source.config_json = {**source.config_json, "connector_enabled": enabled}
        await session.flush()
    return list(sources)
