import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IngestionFailure, SchedulerRun, Source
from app.db.session import get_engine, get_sessionmaker
from app.dlq.service import record_failure
from app.ingestion.lifecycle import run_with_lifecycle
from app.ingestion.normalize import JUSTJOINIT, NOFLUFFJOBS, SOLID_JOBS
from app.ingestion.registry import resolve_source_by_connector
from app.ingestion.types import IngestionResult
from app.scheduler.runs import finish_run_error, finish_run_ok, start_run
from app.scoring import batch
from app.scoring.events import publish_score

logger = logging.getLogger(__name__)

DEFAULT_SOURCE_CONFIGS: dict[str, dict[str, Any]] = {
    SOLID_JOBS: {"schedule": {"type": "interval", "seconds": 300}},
    JUSTJOINIT: {"schedule": {"type": "interval", "seconds": 300}},
    NOFLUFFJOBS: {"schedule": {"type": "interval", "seconds": 300}},
}


async def ensure_sources_exist(session: AsyncSession) -> None:
    for connector, config in DEFAULT_SOURCE_CONFIGS.items():
        stmt = (
            pg_insert(Source)
            .values(name=connector, connector=connector, config_json=config)
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
        if not result.ok:
            await record_failure(
                session,
                IngestionFailure,
                dedup_key=f"source:{source.id}",
                source_id=source.id,
                scheduler_run_id=run.id,
                failure_type="run_fetch_failed",
                error_message=result.error_message or "ingestion failed",
            )
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


async def _run_scoring_job_async() -> batch.BatchScoringSummary:
    """One tick of the dedicated backlog-draining job (own engine/session, like
    `_run_source_async`). Runs on a fixed interval independent of any source's own
    ingestion cadence, so the active profile's backlog keeps draining even when no
    connector happens to fire -- see BUG24.
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


def run_scoring_job_sync() -> batch.BatchScoringSummary:
    return asyncio.run(_run_scoring_job_async())


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
