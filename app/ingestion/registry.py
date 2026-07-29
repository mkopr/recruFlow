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


class DetailRetry(Protocol):
    async def __call__(self, session: AsyncSession, source: Source, url: str) -> bool: ...


@dataclass(frozen=True)
class ConnectorSpec:
    name: str
    label: str
    dispatch: Connector
    seed_config_overrides: dict[str, Any] = field(default_factory=dict)
    # Only connectors with a confirmed live keyword-filter mechanism support Fetch
    # Scope's "filtered" mode -- see CONTEXT.md's Fetch Scope glossary entry.
    supports_fetch_scope: bool = False
    # Only the three detail-page-fetch connectors (Bulldogjob, Rocket Jobs, Pracuj.pl) support
    # retrying one blocked posting URL in isolation -- see US49/`app.dlq.retry`.
    detail_retry: DetailRetry | None = None


_solid_jobs = SolidJobsConnector(campaign=get_settings().solid_jobs_campaign)
_justjoinit = JustJoinItConnector()
_nofluffjobs = NoFluffJobsConnector()
_bulldogjob = BulldogjobConnector()
_rocket_jobs = RocketJobsConnector()
_pracuj = PracujConnector()
_remoteok = RemoteOKConnector()
_remotive = RemotiveConnector()

CONNECTOR_REGISTRY: dict[str, ConnectorSpec] = {
    SOLID_JOBS: ConnectorSpec(
        name=SOLID_JOBS,
        label=_solid_jobs.name,
        dispatch=_solid_jobs.run,
        supports_fetch_scope=True,
    ),
    JUSTJOINIT: ConnectorSpec(name=JUSTJOINIT, label=_justjoinit.name, dispatch=_justjoinit.run),
    NOFLUFFJOBS: ConnectorSpec(
        name=NOFLUFFJOBS, label=_nofluffjobs.name, dispatch=_nofluffjobs.run
    ),
    BULLDOGJOB: ConnectorSpec(
        name=BULLDOGJOB,
        label=_bulldogjob.name,
        dispatch=_bulldogjob.run,
        supports_fetch_scope=True,
        detail_retry=_bulldogjob.retry_detail_fetch,
    ),
    ROCKET_JOBS: ConnectorSpec(
        name=ROCKET_JOBS,
        label=_rocket_jobs.name,
        dispatch=_rocket_jobs.run,
        detail_retry=_rocket_jobs.retry_detail_fetch,
    ),
    PRACUJ: ConnectorSpec(
        name=PRACUJ,
        label=_pracuj.name,
        dispatch=_pracuj.run,
        supports_fetch_scope=True,
        detail_retry=_pracuj.retry_detail_fetch,
        # Browser-driven fetching is far more expensive than every other connector's plain
        # HTTP call (see `docs/adr/0026`), so it gets a longer interval than the
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
        # A single lightweight GET with no pagination cost, so it gets a shorter
        # interval than the shared 300s default.
        seed_config_overrides={"schedule": {"type": "interval", "seconds": 120}},
    ),
    REMOTIVE: ConnectorSpec(
        name=REMOTIVE,
        label=_remotive.name,
        dispatch=_remotive.run,
        # Scopes ingestion to IT-relevant categories by default -- a freshly seeded
        # source should not silently ingest every Remotive category (sales, marketing, ...).
        # `schedule` here is a hard ToS constraint, not a throughput tuning choice like
        # REMOTEOK's or PRACUJ's overrides above: Remotive's API response states usage should
        # not exceed "max. 4 times a day" and warns "excessive requests will be blocked"
        # (confirmed live 2026-07-15) -- 21600s (6h) is exactly that budget, since one
        # run is now a single request (see `RemotiveConnector.fetch_page`).
        seed_config_overrides={
            "schedule": {"type": "interval", "seconds": 21600},
            "categories": list(REMOTIVE_DEFAULT_CATEGORIES),
        },
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
