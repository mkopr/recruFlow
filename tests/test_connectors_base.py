from typing import Any

import pytest
from app.connectors import base
from app.db.models import Source
from app.ingestion import runner
from app.ingestion.types import IngestionResult


class _FixtureConnector(base.JobBoardConnector):
    name = "Fixture"
    envelope_key = "items"

    def default_url(self) -> str:
        return "https://example.test/offers"

    def build_params(
        self, config: dict[str, Any], *, cursor: Any, page_size: int
    ) -> dict[str, Any]:
        return {"cursor": cursor}

    def next_cursor(
        self, payload: Any, offers: list[dict[str, Any]], *, cursor: Any, page_size: int
    ) -> Any | None:
        return None

    def map_offer(self, source_id: int, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "source_id": source_id,
            "title": raw["title"],
            "company": "Acme",
            "canonical_url": raw.get("url"),
        }


def test_fetch_page_returns_offers_and_next_cursor_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(base, "fetch_json", lambda *a, **kw: {"items": [{"title": "a"}]})
    connector = _FixtureConnector()

    assert connector.fetch_page({}, 0, 10) == ([{"title": "a"}], None)


def test_fetch_page_returns_none_on_fetch_json_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(base, "fetch_json", lambda *a, **kw: None)
    connector = _FixtureConnector()

    assert connector.fetch_page({}, 0, 10) is None


def test_fetch_page_logs_and_returns_none_on_unexpected_shape(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(base, "fetch_json", lambda *a, **kw: {"wrong_key": []})
    connector = _FixtureConnector()

    with caplog.at_level("ERROR", logger="app.connectors.base"):
        result = connector.fetch_page({}, 0, 10)

    assert result is None
    assert any(
        "unexpected JSON shape" in r.getMessage() and "Fixture" in r.getMessage()
        for r in caplog.records
    )


@pytest.mark.asyncio
async def test_run_delegates_to_run_paginated_ingestion_with_config_derived_kwargs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def _fake_run_paginated_ingestion(
        session: Any, source_id: int, **kwargs: Any
    ) -> IngestionResult:
        captured.update(kwargs)
        return IngestionResult(ok=True, fetched=0, created=0)

    monkeypatch.setattr(base, "run_paginated_ingestion", _fake_run_paginated_ingestion)

    connector = _FixtureConnector()
    source = Source(
        id=1,
        connector="fixture",
        config_json={"page_size": 50, "max_pages": 3, "already_seen_stop_threshold": 2},
    )

    await connector.run(None, source)  # type: ignore[arg-type]

    assert captured["page_size"] == 50
    assert captured["max_pages"] == 3
    assert captured["already_seen_stop_threshold"] == 2
    assert captured["map_offer"] == connector.map_offer
    assert captured["source_name"] == connector.name
    assert callable(captured["fetch_page"])


@pytest.mark.asyncio
async def test_runner_kwargs_override_wins_over_generic_max_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _MaxPagesOverrideConnector(_FixtureConnector):
        def runner_kwargs(self, config: dict[str, Any]) -> dict[str, Any]:
            return {"max_pages": 1}

    captured: dict[str, Any] = {}

    async def _fake_run_paginated_ingestion(
        session: Any, source_id: int, **kwargs: Any
    ) -> IngestionResult:
        captured.update(kwargs)
        return IngestionResult(ok=True, fetched=0, created=0)

    monkeypatch.setattr(base, "run_paginated_ingestion", _fake_run_paginated_ingestion)

    connector = _MaxPagesOverrideConnector()
    source = Source(id=1, connector="fixture", config_json={"max_pages": 99})

    await connector.run(None, source)  # type: ignore[arg-type]

    assert captured["max_pages"] == 1


@pytest.mark.asyncio
async def test_a_fourth_connector_needs_only_four_methods(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A connector implementing only the 4 abstract methods (no hook overrides) must still
    # ingest end-to-end -- this is the story's own extensibility guarantee (P3US37).
    class _MinimalConnector(base.JobBoardConnector):
        name = "Minimal"
        envelope_key = "items"

        def default_url(self) -> str:
            return "https://example.test/offers"

        def build_params(
            self, config: dict[str, Any], *, cursor: Any, page_size: int
        ) -> dict[str, Any]:
            return {"cursor": cursor}

        def next_cursor(
            self, payload: Any, offers: list[dict[str, Any]], *, cursor: Any, page_size: int
        ) -> Any | None:
            return None

        def map_offer(self, source_id: int, raw: dict[str, Any]) -> dict[str, Any]:
            return {
                "source_id": source_id,
                "title": raw["title"],
                "company": "Acme",
                "canonical_url": raw.get("url"),
            }

    monkeypatch.setattr(
        base,
        "fetch_json",
        lambda *a, **kw: {"items": [{"title": "a", "url": "https://example.test/1"}]},
    )

    async def _fake_ingest_offer(
        session: Any, mapped: dict[str, Any], *, raw_payload: Any
    ) -> tuple[object, bool]:
        return object(), True

    monkeypatch.setattr(runner, "ingest_offer", _fake_ingest_offer)

    connector = _MinimalConnector()
    source = Source(id=1, connector="minimal", config_json={})

    result = await connector.run(None, source)  # type: ignore[arg-type]

    assert result == IngestionResult(ok=True, fetched=1, created=1)
