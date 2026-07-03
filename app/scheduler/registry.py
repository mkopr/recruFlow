from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.connectors.justjoinit import run_justjoinit_ingestion
from app.connectors.nofluffjobs import run_nofluffjobs_ingestion
from app.connectors.solid_jobs import run_solid_jobs_ingestion
from app.db.models import Source
from app.ingestion.normalize import JUSTJOINIT, NOFLUFFJOBS, SOLID_JOBS


class SchedulerLookupError(Exception):
    pass


class UnknownConnectorError(SchedulerLookupError):
    pass


class SourceNotConfiguredError(SchedulerLookupError):
    pass


@dataclass(frozen=True)
class DispatchResult:
    ok: bool
    fetched: int
    created: int


DispatchFn = Callable[[AsyncSession, Source], Awaitable[DispatchResult]]


async def _dispatch_solid_jobs(session: AsyncSession, source: Source) -> DispatchResult:
    result = await run_solid_jobs_ingestion(session, source, campaign=get_settings().sjctl_campaign)
    return DispatchResult(ok=result.ok, fetched=result.fetched, created=result.created)


async def _dispatch_justjoinit(session: AsyncSession, source: Source) -> DispatchResult:
    result = await run_justjoinit_ingestion(session, source)
    return DispatchResult(ok=result.ok, fetched=result.fetched, created=result.created)


async def _dispatch_nofluffjobs(session: AsyncSession, source: Source) -> DispatchResult:
    result = await run_nofluffjobs_ingestion(session, source)
    return DispatchResult(ok=result.ok, fetched=result.fetched, created=result.created)


CONNECTOR_REGISTRY: dict[str, DispatchFn] = {
    SOLID_JOBS: _dispatch_solid_jobs,
    JUSTJOINIT: _dispatch_justjoinit,
    NOFLUFFJOBS: _dispatch_nofluffjobs,
}


async def dispatch_ingestion(session: AsyncSession, source: Source) -> DispatchResult:
    connector = source.connector
    assert connector is not None, "source.connector must be resolved before dispatch"
    dispatch_fn = CONNECTOR_REGISTRY[connector]
    return await dispatch_fn(session, source)


async def resolve_source_by_connector(session: AsyncSession, connector: str) -> Source:
    if connector not in CONNECTOR_REGISTRY:
        raise UnknownConnectorError(f"unknown connector: {connector!r}")

    source = await session.scalar(select(Source).where(Source.connector == connector))
    if source is None:
        raise SourceNotConfiguredError(f"connector {connector!r} has no configured source")

    return source
