from typing import Any

import pytest
from app.connectors import sitemap_detail
from app.connectors.sitemap_detail import SitemapDetailPageConnector
from app.db.models import Source
from app.ingestion.types import IngestionResult


class _FakeSitemapConnector(SitemapDetailPageConnector):
    name = "Fake Sitemap Board"

    def sitemap_url(self) -> str:
        return "https://example.test/sitemap.xml"

    def fetch_sitemap_urls(self, config: dict[str, Any]) -> list[str] | None:
        return ["https://example.test/jobs/1", "https://example.test/jobs/2"]

    def extract_detail_json(self, html: str, *, url: str | None) -> dict[str, Any] | None:
        return {"title": "Backend Engineer", "url": url}

    def map_offer(self, source_id: int, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "source_id": source_id,
            "title": raw.get("title") or "",
            "company": "Acme",
            "canonical_url": raw.get("url"),
        }


def test_follow_redirects_on_detail_fetch_defaults_false() -> None:
    assert _FakeSitemapConnector().follow_redirects_on_detail_fetch() is False


def test_default_url_delegates_to_sitemap_url() -> None:
    assert _FakeSitemapConnector().build_url({}) == "https://example.test/sitemap.xml"


def test_build_params_returns_empty_dict() -> None:
    assert _FakeSitemapConnector().build_params({}, cursor=0, page_size=20) == {}


def test_next_cursor_always_none() -> None:
    connector = _FakeSitemapConnector()

    assert connector.next_cursor({}, [{"title": "a"}], cursor=0, page_size=20) is None


@pytest.mark.asyncio
async def test_run_enumerates_fetches_and_persists_cursor_via_minimal_fake_subclass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _FakeSitemapConnector, "_fetch_detail_html", lambda self, url: f"<html>{url}</html>"
    )

    captured: dict[str, Any] = {}

    async def _fake_run_paginated_ingestion(
        session: Any, source_id: int, **kwargs: Any
    ) -> IngestionResult:
        captured.update(kwargs)
        return IngestionResult(ok=True, fetched=0, created=0)

    monkeypatch.setattr(sitemap_detail, "run_paginated_ingestion", _fake_run_paginated_ingestion)

    connector = _FakeSitemapConnector()
    source = Source(id=1, connector="fake_sitemap", config_json={})

    await connector.run(None, source)  # type: ignore[arg-type]

    assert captured["page_size"] == 20
    assert captured["max_pages"] == 50
    assert captured["already_seen_stop_threshold"] == 20
    fetch_page = captured["fetch_page"]
    assert callable(fetch_page)

    offers, next_cursor = fetch_page(0, 20)
    assert offers == [
        {"title": "Backend Engineer", "url": "https://example.test/jobs/1"},
        {"title": "Backend Engineer", "url": "https://example.test/jobs/2"},
    ]
    assert next_cursor is None
    assert source.config_json["sitemap_cursor"] == 0


@pytest.mark.asyncio
async def test_run_reads_kwargs_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_FakeSitemapConnector, "fetch_sitemap_urls", lambda self, config: [])

    captured: dict[str, Any] = {}

    async def _fake_run_paginated_ingestion(
        session: Any, source_id: int, **kwargs: Any
    ) -> IngestionResult:
        captured.update(kwargs)
        return IngestionResult(ok=True, fetched=0, created=0)

    monkeypatch.setattr(sitemap_detail, "run_paginated_ingestion", _fake_run_paginated_ingestion)

    connector = _FakeSitemapConnector()
    source = Source(
        id=1,
        connector="fake_sitemap",
        config_json={"page_size": 5, "max_pages": 3, "already_seen_stop_threshold": 2},
    )

    await connector.run(None, source)  # type: ignore[arg-type]

    assert captured["page_size"] == 5
    assert captured["max_pages"] == 3
    assert captured["already_seen_stop_threshold"] == 2


@pytest.mark.asyncio
async def test_run_returns_not_ok_when_sitemap_fetch_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_FakeSitemapConnector, "fetch_sitemap_urls", lambda self, config: None)

    connector = _FakeSitemapConnector()
    source = Source(id=1, connector="fake_sitemap", config_json={})

    result = await connector.run(None, source)  # type: ignore[arg-type]

    assert result == IngestionResult(
        ok=False, fetched=0, created=0, error_message="failed to fetch Fake Sitemap Board offers"
    )


@pytest.mark.asyncio
async def test_run_persists_zero_cursor_when_sitemap_fully_walked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A sitemap shorter than page_size is walked to completion in one page, so `fetch_page`
    # returns a `None` next cursor -- `next_sitemap_cursor` must wrap that to 0 (BUG41), not
    # leak `None` into `config_json["sitemap_cursor"]`.
    monkeypatch.setattr(
        _FakeSitemapConnector, "_fetch_detail_html", lambda self, url: f"<html>{url}</html>"
    )

    async def _fake_run_paginated_ingestion(
        session: Any, source_id: int, **kwargs: Any
    ) -> IngestionResult:
        return IngestionResult(ok=True, fetched=0, created=0)

    monkeypatch.setattr(sitemap_detail, "run_paginated_ingestion", _fake_run_paginated_ingestion)

    connector = _FakeSitemapConnector()
    source = Source(id=1, connector="fake_sitemap", config_json={"page_size": 20})

    await connector.run(None, source)  # type: ignore[arg-type]

    assert source.config_json["sitemap_cursor"] == 0
