from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.connectors import we_work_remotely
from app.connectors.bulldogjob import BulldogjobConnector
from app.connectors.justjoinit import JustJoinItConnector
from app.connectors.nofluffjobs import NoFluffJobsConnector
from app.connectors.pracuj import PracujConnector
from app.connectors.remoteok import RemoteOKConnector
from app.connectors.remotive import DEFAULT_CATEGORIES as REMOTIVE_DEFAULT_CATEGORIES
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
    WE_WORK_REMOTELY,
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
    seed_config_overrides: dict[str, Any] = field(default_factory=dict)


_solid_jobs = SolidJobsConnector(campaign=get_settings().solid_jobs_campaign)
_justjoinit = JustJoinItConnector()
_nofluffjobs = NoFluffJobsConnector()
_bulldogjob = BulldogjobConnector()
_rocket_jobs = RocketJobsConnector()
_pracuj = PracujConnector()
_remoteok = RemoteOKConnector()
_remotive = RemotiveConnector()

CONNECTOR_REGISTRY: dict[str, ConnectorSpec] = {
    SOLID_JOBS: ConnectorSpec(name=SOLID_JOBS, label=_solid_jobs.name, dispatch=_solid_jobs.run),
    JUSTJOINIT: ConnectorSpec(name=JUSTJOINIT, label=_justjoinit.name, dispatch=_justjoinit.run),
    NOFLUFFJOBS: ConnectorSpec(
        name=NOFLUFFJOBS, label=_nofluffjobs.name, dispatch=_nofluffjobs.run
    ),
    BULLDOGJOB: ConnectorSpec(name=BULLDOGJOB, label=_bulldogjob.name, dispatch=_bulldogjob.run),
    ROCKET_JOBS: ConnectorSpec(
        name=ROCKET_JOBS, label=_rocket_jobs.name, dispatch=_rocket_jobs.run
    ),
    PRACUJ: ConnectorSpec(
        name=PRACUJ,
        label=_pracuj.name,
        dispatch=_pracuj.run,
        # Browser-driven fetching is far more expensive than every other connector's plain
        # HTTP call (P3US41, see `docs/adr/0026`), so it gets a longer interval than the
        # shared 300s default -- the same "expensive, throttle hard" rationale ADR 0024/0026
        # established for this operator's Cloudflare tuning -- and a non-empty
        # `category_filter` so a freshly seeded source doesn't immediately ingest every
        # industry Pracuj.pl lists, not just IT.
        seed_config_overrides={
            "schedule": {"type": "interval", "seconds": 3600},
            "category_filter": "it",
        },
    ),
    REMOTEOK: ConnectorSpec(
        name=REMOTEOK,
        label=_remoteok.name,
        dispatch=_remoteok.run,
        # A single lightweight GET with no pagination cost (P3US42), so it gets a shorter
        # interval than the shared 300s default.
        seed_config_overrides={"schedule": {"type": "interval", "seconds": 120}},
    ),
    REMOTIVE: ConnectorSpec(
        name=REMOTIVE,
        label=_remotive.name,
        dispatch=_remotive.run,
        # Scopes ingestion to IT-relevant categories by default (P3US43) -- a freshly seeded
        # source should not silently ingest every Remotive category (sales, marketing, ...).
        seed_config_overrides={"categories": list(REMOTIVE_DEFAULT_CATEGORIES)},
    ),
    # implements Connector directly, see we_work_remotely.py module docstring
    WE_WORK_REMOTELY: ConnectorSpec(
        name=WE_WORK_REMOTELY,
        label=we_work_remotely.NAME,
        dispatch=we_work_remotely.run_we_work_remotely_ingestion,
    ),
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
