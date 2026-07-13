import logging
from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.http import fetch_json
from app.db.models import Source
from app.ingestion.normalize import extract_envelope_list
from app.ingestion.runner import resolve_fetch_range, run_paginated_ingestion
from app.ingestion.types import IngestionResult

logger = logging.getLogger(__name__)


class JobBoardConnector(ABC):
    """Template Method shared by every job board connector (P3US37, see
    `docs/adr/0021-jobboardconnector-template-method-boundary.md`).

    `fetch_page` and `run` are fixed -- they implement the fetch -> extract ->
    log-on-failure -> next-cursor loop and the config-read -> dispatch skeleton exactly
    once, so a subclass cannot reimplement (and accidentally diverge on) the parts that
    must stay identical across every connector. Everything a connector genuinely varies on
    is either abstract (no sensible default) or a hook (sensible default, override only
    when the underlying API needs a twist).
    """

    name: str
    envelope_key: str = ""

    @abstractmethod
    def default_url(self) -> str: ...

    @abstractmethod
    def build_params(
        self, config: dict[str, Any], *, cursor: Any, page_size: int
    ) -> dict[str, Any]: ...

    @abstractmethod
    def next_cursor(
        self, payload: Any, offers: list[dict[str, Any]], *, cursor: Any, page_size: int
    ) -> Any | None: ...

    @abstractmethod
    def map_offer(self, source_id: int, raw: dict[str, Any]) -> dict[str, Any]: ...

    def build_url(self, config: dict[str, Any]) -> str:
        return str(config.get("endpoint_url", self.default_url()))

    def build_headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {}

    def extract_offers(self, payload: Any) -> list[dict[str, Any]] | None:
        return extract_envelope_list(payload, self.envelope_key)

    def runner_kwargs(self, config: dict[str, Any]) -> dict[str, Any]:
        return {}

    def fetch_page(
        self, config: dict[str, Any], cursor: Any, page_size: int
    ) -> tuple[list[dict[str, Any]], Any | None] | None:
        url = self.build_url(config)
        params = self.build_params(config, cursor=cursor, page_size=page_size)
        headers = self.build_headers(config)
        payload = fetch_json(
            url, source_name=self.name, logger=logger, params=params, headers=headers
        )
        if payload is None:
            return None

        offers = self.extract_offers(payload)
        if offers is None:
            logger.error(
                "%s returned unexpected JSON shape: url=%r cursor=%r", self.name, url, cursor
            )
            return None

        return offers, self.next_cursor(payload, offers, cursor=cursor, page_size=page_size)

    async def run(
        self, session: AsyncSession, source: Source, force_refresh: bool = False
    ) -> IngestionResult:
        config = source.config_json or {}
        since, until = resolve_fetch_range(config.get("fetch_range"))

        runner_kwargs: dict[str, Any] = {
            "page_size": int(config.get("page_size", 100)),
            "max_pages": int(config.get("max_pages", 100)),
            "already_seen_stop_threshold": int(config.get("already_seen_stop_threshold", 20)),
            **self.runner_kwargs(config),
        }

        def fetch_page(
            cursor: Any, page_size: int
        ) -> tuple[list[dict[str, Any]], Any | None] | None:
            return self.fetch_page(config, cursor, page_size)

        return await run_paginated_ingestion(
            session,
            source.id,
            source_name=self.name,
            fetch_page=fetch_page,
            map_offer=self.map_offer,
            initial_cursor=0,
            force_refresh=force_refresh,
            logger=logger,
            since=since,
            until=until,
            **runner_kwargs,
        )
