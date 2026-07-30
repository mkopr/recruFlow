from typing import Any

import httpx
import pytest
from app.connectors import sitemap_detail
from app.connectors.http import BlockedFetchError
from app.connectors.proxy_pool import ProxyPool
from app.connectors.sitemap_detail import SitemapDetailPageConnector
from app.db.models import Source
from app.dlq.types import FailureType
from app.ingestion.types import IngestionResult

from tests.conftest import TEST_PROXY


class _FakeResponse:
    def __init__(self, *, text: str = "", status_error: Exception | None = None) -> None:
        self.text = text
        self._status_error = status_error

    def raise_for_status(self) -> None:
        if self._status_error is not None:
            raise self._status_error


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
    # returns a `None` next cursor -- `next_sitemap_cursor` must wrap that to 0, not leak `None`
    # into `config_json["sitemap_cursor"]`.
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


@pytest.mark.asyncio
async def test_fetch_page_records_blocked_url_and_continues_when_detail_fetch_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_fetch_detail_html(self: Any, url: str) -> str | None:
        if url == "https://example.test/jobs/1":
            raise BlockedFetchError(403)
        return f"<html>{url}</html>"

    monkeypatch.setattr(_FakeSitemapConnector, "_fetch_detail_html", _fake_fetch_detail_html)

    captured: dict[str, Any] = {}

    async def _fake_run_paginated_ingestion(
        session: Any, source_id: int, **kwargs: Any
    ) -> IngestionResult:
        fetch_page = kwargs["fetch_page"]
        offers, _next_cursor = fetch_page(kwargs["initial_cursor"], kwargs["page_size"])
        captured["offers"] = offers
        return IngestionResult(ok=True, fetched=len(offers), created=0)

    monkeypatch.setattr(sitemap_detail, "run_paginated_ingestion", _fake_run_paginated_ingestion)

    recorded: list[dict[str, Any]] = []

    async def _fake_record_failure(session: Any, model_cls: Any, **fields: Any) -> None:
        recorded.append(fields)

    monkeypatch.setattr(sitemap_detail, "record_failure", _fake_record_failure)

    connector = _FakeSitemapConnector()
    source = Source(id=1, connector="fake_sitemap", config_json={})

    await connector.run(None, source)  # type: ignore[arg-type]

    # The blocked URL is excluded from the offers that get persisted -- only the other one
    # made it through.
    assert captured["offers"] == [
        {"title": "Backend Engineer", "url": "https://example.test/jobs/2"},
    ]
    assert len(recorded) == 1
    assert recorded[0]["url"] == "https://example.test/jobs/1"
    assert recorded[0]["blocked_status"] == 403
    assert recorded[0]["failure_type"] == FailureType.DETAIL_FETCH_BLOCKED
    assert recorded[0]["source_id"] == 1


@pytest.mark.asyncio
async def test_run_returns_blocked_status_when_sitemap_fetch_itself_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail(self: Any, config: dict[str, Any]) -> list[str] | None:
        raise BlockedFetchError(429)

    monkeypatch.setattr(_FakeSitemapConnector, "fetch_sitemap_urls", _fail)

    connector = _FakeSitemapConnector()
    source = Source(id=1, connector="fake_sitemap", config_json={})

    result = await connector.run(None, source)  # type: ignore[arg-type]

    assert result.ok is False
    assert result.blocked_status == 429


def test_fetch_detail_html_reports_failure_to_shared_pool_on_http_status_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = ProxyPool()
    pool._good = [TEST_PROXY]
    monkeypatch.setattr(sitemap_detail, "_proxy_pool", pool)

    request = httpx.Request("GET", "https://example.test/jobs/1")
    status_error = httpx.HTTPStatusError(
        "server error", request=request, response=httpx.Response(500, request=request)
    )
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(status_error=status_error))

    connector = _FakeSitemapConnector()

    result = connector._fetch_detail_html("https://example.test/jobs/1")

    assert result is None
    assert sitemap_detail._proxy_pool.size() == 0


def test_fetch_detail_html_does_not_report_failure_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = ProxyPool()
    pool._good = [TEST_PROXY]
    monkeypatch.setattr(sitemap_detail, "_proxy_pool", pool)
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(text="<html>ok</html>"))

    connector = _FakeSitemapConnector()

    result = connector._fetch_detail_html("https://example.test/jobs/1")

    assert result == "<html>ok</html>"
    assert sitemap_detail._proxy_pool.size() == 1


def test_supports_detail_retry_is_true() -> None:
    assert _FakeSitemapConnector().supports_detail_retry() is True


@pytest.mark.asyncio
async def test_retry_detail_fetch_returns_false_when_html_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_FakeSitemapConnector, "_fetch_detail_html", lambda self, url: None)

    connector = _FakeSitemapConnector()
    source = Source(id=1, connector="fake_sitemap", config_json={})

    result = await connector.retry_detail_fetch(
        None,  # type: ignore[arg-type]
        source,
        "https://example.test/jobs/1",
    )

    assert result is False
