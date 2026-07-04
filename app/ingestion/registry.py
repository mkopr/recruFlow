from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.connectors import justjoinit, nofluffjobs, solid_jobs
from app.db.models import Source
from app.ingestion.normalize import JUSTJOINIT, NOFLUFFJOBS, SOLID_JOBS
from app.ingestion.types import IngestionResult


class SchedulerLookupError(Exception):
    pass


class UnknownConnectorError(SchedulerLookupError):
    pass


class SourceNotConfiguredError(SchedulerLookupError):
    pass


class Connector(Protocol):
    async def __call__(
        self, session: AsyncSession, source: Source, force_refresh: bool
    ) -> IngestionResult: ...


async def _dispatch_solid_jobs(
    session: AsyncSession, source: Source, force_refresh: bool
) -> IngestionResult:
    return await solid_jobs.run_solid_jobs_ingestion(
        session, source, campaign=get_settings().sjctl_campaign, force_refresh=force_refresh
    )


async def _dispatch_justjoinit(
    session: AsyncSession, source: Source, force_refresh: bool
) -> IngestionResult:
    return await justjoinit.run_justjoinit_ingestion(session, source)


async def _dispatch_nofluffjobs(
    session: AsyncSession, source: Source, force_refresh: bool
) -> IngestionResult:
    return await nofluffjobs.run_nofluffjobs_ingestion(session, source)


CONNECTOR_REGISTRY: dict[str, Connector] = {
    SOLID_JOBS: _dispatch_solid_jobs,
    JUSTJOINIT: _dispatch_justjoinit,
    NOFLUFFJOBS: _dispatch_nofluffjobs,
}


async def dispatch_ingestion(
    session: AsyncSession, source: Source, *, force_refresh: bool = False
) -> IngestionResult:
    connector = source.connector
    assert connector is not None, "source.connector must be resolved before dispatch"
    dispatch_fn = CONNECTOR_REGISTRY[connector]
    return await dispatch_fn(session, source, force_refresh)


async def resolve_source_by_connector(session: AsyncSession, connector: str) -> Source:
    if connector not in CONNECTOR_REGISTRY:
        raise UnknownConnectorError(f"unknown connector: {connector!r}")

    source = await session.scalar(select(Source).where(Source.connector == connector))
    if source is None:
        raise SourceNotConfiguredError(f"connector {connector!r} has no configured source")

    return source
