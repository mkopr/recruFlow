from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.connectors.bulldogjob import BulldogjobConnector
from app.connectors.justjoinit import JustJoinItConnector
from app.connectors.nofluffjobs import NoFluffJobsConnector
from app.connectors.pracuj import PracujConnector
from app.connectors.remoteok import RemoteOKConnector
from app.connectors.remotive import RemotiveConnector
from app.connectors.rocket_jobs import RocketJobsConnector
from app.connectors.solid_jobs import SolidJobsConnector
from app.db.models import Source
from app.ingestion.normalize import (
    BULLDOGJOB,
    JUSTJOINIT,
    NOFLUFFJOBS,
    PRACUJ,
    REMOTEOK,
    REMOTIVE,
    ROCKET_JOBS,
    SOLID_JOBS,
)
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


@dataclass(frozen=True)
class ConnectorSpec:
    name: str
    label: str
    dispatch: Connector


CONNECTOR_REGISTRY: dict[str, ConnectorSpec] = {
    SOLID_JOBS: ConnectorSpec(
        name=SOLID_JOBS,
        label="SOLID.Jobs",
        dispatch=SolidJobsConnector(campaign=get_settings().solid_jobs_campaign).run,
    ),
    JUSTJOINIT: ConnectorSpec(
        name=JUSTJOINIT, label="JustJoin.it", dispatch=JustJoinItConnector().run
    ),
    NOFLUFFJOBS: ConnectorSpec(
        name=NOFLUFFJOBS, label="NoFluffJobs", dispatch=NoFluffJobsConnector().run
    ),
    BULLDOGJOB: ConnectorSpec(
        name=BULLDOGJOB, label="Bulldogjob", dispatch=BulldogjobConnector().run
    ),
    ROCKET_JOBS: ConnectorSpec(
        name=ROCKET_JOBS, label="Rocket Jobs", dispatch=RocketJobsConnector().run
    ),
    PRACUJ: ConnectorSpec(name=PRACUJ, label="Pracuj.pl", dispatch=PracujConnector().run),
    REMOTEOK: ConnectorSpec(name=REMOTEOK, label="RemoteOK", dispatch=RemoteOKConnector().run),
    REMOTIVE: ConnectorSpec(name=REMOTIVE, label="Remotive", dispatch=RemotiveConnector().run),
}


async def dispatch_ingestion(
    session: AsyncSession, source: Source, *, force_refresh: bool = False
) -> IngestionResult:
    connector = source.connector
    assert connector is not None, "source.connector must be resolved before dispatch"
    spec = CONNECTOR_REGISTRY[connector]
    return await spec.dispatch(session, source, force_refresh)


async def resolve_source_by_connector(session: AsyncSession, connector: str) -> Source:
    if connector not in CONNECTOR_REGISTRY:
        raise UnknownConnectorError(f"unknown connector: {connector!r}")

    source = await session.scalar(select(Source).where(Source.connector == connector))
    if source is None:
        raise SourceNotConfiguredError(f"connector {connector!r} has no configured source")

    return source
