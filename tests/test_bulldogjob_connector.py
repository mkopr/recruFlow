import gzip
from typing import Any

import httpx
import pytest
from app.connectors import bulldogjob
from app.connectors.bulldogjob import (
    BULLDOGJOB_SITEMAP_INDEX_URL,
    BulldogjobConnector,
    extract_next_data,
)
from app.connectors.http import fetch_gzip_xml
from app.ingestion.normalize import BULLDOGJOB

# Trimmed from a real fetched detail page (confirmed live 2026-07-13):
# https://bulldogjob.com/companies/jobs/243779-java-technical-leader-warsaw-devire
_REAL_NEXT_DATA: dict[str, Any] = {
    "props": {
        "pageProps": {
            "data": {
                "job": {
                    "id": "243779-java-technical-leader-warsaw-devire",
                    "position": "Java Technical Leader",
                    "experienceLevel": "lead",
                    "remote": False,
                    "publishedAt": "2026-06-13T08:30:09+02:00",
                    "offer": "<ul><li>Hybrid work.</li></ul>",
                    "requirements": "<ul><li>Several years of Java experience.</li></ul>",
                    "company": {"name": "Devire"},
                    "locations": [
                        {"location": {"cityEn": "Warsaw"}},
                    ],
                    "employmentSalary": None,
                    "b2bSalary": {
                        "currency": "PLN",
                        "minValue": None,
                        "maxValue": None,
                        "money": "180 - 200",
                        "timeframe": "hour",
                    },
                    "otherSalary": None,
                }
            }
        }
    }
}

_NEXT_DATA_HTML = (
    '<html><body><script id="__NEXT_DATA__" type="application/json">'
    '{"props": {"pageProps": {"data": {"job": {"id": "1-a", "position": "Backend Engineer"}}}}}'
    "</script></body></html>"
)


def _gzip_xml(xml_text: str) -> bytes:
    return gzip.compress(xml_text.encode("utf-8"))


class _FakeResponse:
    def __init__(
        self, *, content: bytes = b"", text: str = "", status_error: Exception | None = None
    ) -> None:
        self.content = content
        self.text = text
        self._status_error = status_error

    def raise_for_status(self) -> None:
        if self._status_error is not None:
            raise self._status_error


def test_default_url_is_the_bulldogjob_sitemap_index() -> None:
    assert BulldogjobConnector().build_url({}) == BULLDOGJOB_SITEMAP_INDEX_URL


def test_build_url_honors_endpoint_url_override_from_config() -> None:
    connector = BulldogjobConnector()

    assert connector.build_url({"endpoint_url": "https://example.test/sitemap.xml.gz"}) == (
        "https://example.test/sitemap.xml.gz"
    )


def test_next_cursor_always_none() -> None:
    connector = BulldogjobConnector()

    assert connector.next_cursor({}, [{"title": "a"}], cursor=0, page_size=20) is None


def test_build_params_returns_empty_dict() -> None:
    connector = BulldogjobConnector()

    assert connector.build_params({}, cursor=0, page_size=20) == {}


def test_fetch_sitemap_urls_returns_urls_from_fixture_gzip_sitemap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index_xml = (
        '<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<sitemap><loc>https://bulldogjob.com/en/jobs.xml.gz</loc></sitemap>"
        "</sitemapindex>"
    )
    jobs_xml = (
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://bulldogjob.com/companies/jobs/1-a</loc></url>"
        "<url><loc>https://bulldogjob.com/companies/jobs/2-b</loc></url>"
        "<url><loc>https://bulldogjob.com/companies/jobs/s/skills,Java</loc></url>"
        "</urlset>"
    )

    def _fake_get(url: str, **kwargs: Any) -> _FakeResponse:
        if url == BULLDOGJOB_SITEMAP_INDEX_URL:
            return _FakeResponse(content=_gzip_xml(index_xml))
        if url == "https://bulldogjob.com/en/jobs.xml.gz":
            return _FakeResponse(content=_gzip_xml(jobs_xml))
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(httpx, "get", _fake_get)

    result = BulldogjobConnector().fetch_sitemap_urls({})

    assert result == [
        "https://bulldogjob.com/companies/jobs/1-a",
        "https://bulldogjob.com/companies/jobs/2-b",
    ]


def test_fetch_sitemap_urls_returns_none_on_index_fetch_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(*a: Any, **kw: Any) -> None:
        raise httpx.ConnectError("connection failed")

    monkeypatch.setattr(httpx, "get", _raise)

    assert BulldogjobConnector().fetch_sitemap_urls({}) is None


def test_fetch_sitemap_urls_returns_none_on_malformed_gzip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(content=b"not gzip"))

    assert (
        fetch_gzip_xml(
            BULLDOGJOB_SITEMAP_INDEX_URL, source_name="Bulldogjob", logger=bulldogjob.logger
        )
        is None
    )
    assert BulldogjobConnector().fetch_sitemap_urls({}) is None


def test_extract_next_data_returns_parsed_json_for_wellformed_fixture() -> None:
    result = extract_next_data(_NEXT_DATA_HTML)

    assert result == {
        "props": {"pageProps": {"data": {"job": {"id": "1-a", "position": "Backend Engineer"}}}}
    }


def test_extract_next_data_returns_none_and_logs_when_script_tag_missing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("ERROR", logger="app.connectors.bulldogjob"):
        result = extract_next_data("<html><body>no next data here</body></html>", url="https://x")

    assert result is None
    assert any(
        "Bulldogjob returned unexpected page shape" in r.getMessage() for r in caplog.records
    )


def test_extract_next_data_returns_none_on_malformed_json_inside_script_tag(
    caplog: pytest.LogCaptureFixture,
) -> None:
    html = '<script id="__NEXT_DATA__" type="application/json">{not valid json</script>'

    with caplog.at_level("ERROR", logger="app.connectors.bulldogjob"):
        result = extract_next_data(html, url="https://x")

    assert result is None
    assert any(
        "Bulldogjob returned unexpected page shape" in r.getMessage() for r in caplog.records
    )


def test_map_bulldogjob_offer_maps_all_known_fields() -> None:
    result = BulldogjobConnector().map_offer(1, _REAL_NEXT_DATA)

    assert result == {
        "source_id": 1,
        "external_id": "243779-java-technical-leader-warsaw-devire",
        "canonical_url": "https://bulldogjob.com/companies/jobs/243779-java-technical-leader-warsaw-devire",
        "title": "Java Technical Leader",
        "company": "Devire",
        "location": "Warsaw",
        "remote": False,
        "seniority": "lead",
        "salary_min": None,
        "salary_max": None,
        "salary_currency": "PLN",
        "contract_type": "b2b",
        "posted_at": "2026-06-13T08:30:09+02:00",
        "description": (
            "<ul><li>Hybrid work.</li></ul>\n\n<ul><li>Several years of Java experience.</li></ul>"
        ),
    }


def test_map_bulldogjob_offer_maps_remote_boolean_directly() -> None:
    raw = {
        "props": {
            "pageProps": {
                "data": {
                    "job": {
                        "id": "1-a",
                        "position": "x",
                        "company": {"name": "y"},
                        "remote": True,
                    }
                }
            }
        }
    }

    assert BulldogjobConnector().map_offer(1, raw)["remote"] is True


def test_map_bulldogjob_offer_handles_missing_optional_fields() -> None:
    raw = {
        "props": {
            "pageProps": {
                "data": {"job": {"position": "Backend Engineer", "company": {"name": "Acme"}}}
            }
        }
    }

    result = BulldogjobConnector().map_offer(1, raw)

    assert result["external_id"] is None
    assert result["canonical_url"] is None
    assert result["location"] is None
    assert result["seniority"] is None
    assert result["salary_min"] is None
    assert result["salary_max"] is None
    assert result["contract_type"] is None
    assert result["posted_at"] is None
    assert result["description"] is None
    assert result["salary_currency"] == "PLN"
    assert result["remote"] is False


def test_map_bulldogjob_offer_handles_completely_unexpected_shape() -> None:
    # e.g. a sitemap-listed filter/tag page (`/companies/jobs/s/skills,Java`) that has a
    # `__NEXT_DATA__` blob but no `job` record -- must degrade to empty-ish fields, not crash.
    result = BulldogjobConnector().map_offer(1, {})

    assert result["title"] == ""
    assert result["company"] == ""
    assert result["canonical_url"] is None


def test_map_bulldogjob_offer_calls_shared_normalize_functions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, tuple[Any, ...]] = {}

    def _record(name: str) -> Any:
        def _stub(*args: Any, **kwargs: Any) -> Any:
            calls[name] = args
            if name == "normalize_salary":
                return (None, None, "PLN")
            if name == "normalize_seniority":
                return None
            return False

        return _stub

    monkeypatch.setattr(bulldogjob, "normalize_remote", _record("normalize_remote"))
    monkeypatch.setattr(bulldogjob, "normalize_seniority", _record("normalize_seniority"))
    monkeypatch.setattr(bulldogjob, "normalize_salary", _record("normalize_salary"))

    BulldogjobConnector().map_offer(1, _REAL_NEXT_DATA)

    assert calls["normalize_remote"][0] == BULLDOGJOB
    assert calls["normalize_seniority"][0] == BULLDOGJOB
    assert calls["normalize_salary"][0] == BULLDOGJOB


@pytest.mark.asyncio
async def test_bulldogjob_run_delegates_to_run_paginated_ingestion_with_sitemap_derived_fetch_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db.models import Source
    from app.ingestion.types import IngestionResult

    monkeypatch.setattr(
        BulldogjobConnector,
        "fetch_sitemap_urls",
        lambda self, config: ["https://x/1", "https://x/2"],
    )

    captured: dict[str, Any] = {}

    async def _fake_run_paginated_ingestion(
        session: Any, source_id: int, **kwargs: Any
    ) -> IngestionResult:
        captured.update(kwargs)
        return IngestionResult(ok=True, fetched=0, created=0)

    monkeypatch.setattr(bulldogjob, "run_paginated_ingestion", _fake_run_paginated_ingestion)

    connector = BulldogjobConnector()
    source = Source(id=1, connector="bulldogjob", config_json={})

    await connector.run(None, source)  # type: ignore[arg-type]

    assert captured["page_size"] == 20
    assert captured["max_pages"] == 50
    assert captured["already_seen_stop_threshold"] == 20
    assert callable(captured["fetch_page"])


@pytest.mark.asyncio
async def test_bulldogjob_run_reads_kwargs_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.db.models import Source
    from app.ingestion.types import IngestionResult

    monkeypatch.setattr(BulldogjobConnector, "fetch_sitemap_urls", lambda self, config: [])

    captured: dict[str, Any] = {}

    async def _fake_run_paginated_ingestion(
        session: Any, source_id: int, **kwargs: Any
    ) -> IngestionResult:
        captured.update(kwargs)
        return IngestionResult(ok=True, fetched=0, created=0)

    monkeypatch.setattr(bulldogjob, "run_paginated_ingestion", _fake_run_paginated_ingestion)

    connector = BulldogjobConnector()
    source = Source(
        id=1,
        connector="bulldogjob",
        config_json={"page_size": 5, "max_pages": 3, "already_seen_stop_threshold": 2},
    )

    await connector.run(None, source)  # type: ignore[arg-type]

    assert captured["page_size"] == 5
    assert captured["max_pages"] == 3
    assert captured["already_seen_stop_threshold"] == 2


@pytest.mark.asyncio
async def test_bulldogjob_run_returns_not_ok_when_sitemap_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db.models import Source
    from app.ingestion.types import IngestionResult

    monkeypatch.setattr(BulldogjobConnector, "fetch_sitemap_urls", lambda self, config: None)

    connector = BulldogjobConnector()
    source = Source(id=1, connector="bulldogjob", config_json={})

    result = await connector.run(None, source)  # type: ignore[arg-type]

    assert result == IngestionResult(
        ok=False, fetched=0, created=0, error_message="failed to fetch Bulldogjob offers"
    )
