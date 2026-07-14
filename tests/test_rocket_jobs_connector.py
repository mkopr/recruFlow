import ast
import inspect
from typing import Any

import httpx
import pytest
from app.connectors import rocket_jobs
from app.connectors.rocket_jobs import (
    ROCKET_JOBS_SITEMAP_URL,
    RocketJobsConnector,
    extract_job_posting_json_ld,
)
from app.ingestion.normalize import ROCKET_JOBS

# Fields confirmed present in a real fetched Rocket Jobs detail page's JSON-LD block
# (schema.org JobPosting shape), sampled live across several detail pages 2026-07-14: never a
# `url`, `baseSalary`, `jobLocationType`, or `experienceRequirements` key. `_source_url` is not
# part of the real JSON-LD -- it's what `run`'s `fetch_page` closure injects before persisting,
# simulated here directly since this fixture exercises `map_offer` in isolation.
_REAL_JOB_POSTING: dict[str, Any] = {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    "title": "Senior Backend Engineer",
    "description": "<p>We are looking for a Senior Backend Engineer.</p>",
    "datePosted": "2026-06-20T10:00:00+02:00",
    "validThrough": "2026-07-20T10:00:00+02:00",
    "employmentType": "FULL_TIME",
    "hiringOrganization": {"@type": "Organization", "name": "Acme"},
    "jobLocation": {
        "@type": "Place",
        "address": {
            "@type": "PostalAddress",
            "addressLocality": "Warszawa",
            "addressCountry": "PL",
        },
    },
    "_source_url": "https://rocketjobs.pl/oferta-pracy/senior-backend-engineer-acme-warszawa",
}

_JSON_LD_HTML = (
    '<html><body><script type="application/ld+json">'
    '{"@type": "JobPosting", "title": "Backend Engineer", '
    '"url": "https://rocketjobs.pl/oferty-pracy/backend-engineer"}'
    "</script></body></html>"
)


class _FakeResponse:
    def __init__(self, *, text: str = "", status_error: Exception | None = None) -> None:
        self.text = text
        self._status_error = status_error

    def raise_for_status(self) -> None:
        if self._status_error is not None:
            raise self._status_error


def _index_sitemap_xml(url: str) -> str:
    return (
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{url}</loc></url>"
        "</urlset>"
    )


def test_default_url_is_the_rocket_jobs_sitemap_url() -> None:
    assert RocketJobsConnector().build_url({}) == ROCKET_JOBS_SITEMAP_URL


def test_build_url_honors_endpoint_url_override_from_config() -> None:
    connector = RocketJobsConnector()

    assert connector.build_url({"endpoint_url": "https://example.test/active-jobs.xml"}) == (
        "https://example.test/active-jobs.xml"
    )


def test_next_cursor_always_none() -> None:
    connector = RocketJobsConnector()

    assert connector.next_cursor({}, [{"title": "a"}], cursor=0, page_size=20) is None


def test_build_params_returns_empty_dict() -> None:
    connector = RocketJobsConnector()

    assert connector.build_params({}, cursor=0, page_size=20) == {}


def test_fetch_sitemap_urls_returns_urls_from_fixture_sitemap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urlset_xml = (
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://rocketjobs.pl/oferty-pracy/job-1</loc></url>"
        "<url><loc>https://rocketjobs.pl/oferty-pracy/job-2</loc></url>"
        "</urlset>"
    )

    def _fake_get(url: str, **kwargs: Any) -> _FakeResponse:
        if url == ROCKET_JOBS_SITEMAP_URL:
            return _FakeResponse(text=urlset_xml)
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(httpx, "get", _fake_get)

    result = RocketJobsConnector().fetch_sitemap_urls({})

    assert result == [
        "https://rocketjobs.pl/oferty-pracy/job-1",
        "https://rocketjobs.pl/oferty-pracy/job-2",
    ]


def test_fetch_sitemap_urls_follows_redirect_or_index_chain_to_all_parts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index_xml = (
        '<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<sitemap><loc>https://rocketjobs.pl/sitemaps/part0.xml</loc></sitemap>"
        "<sitemap><loc>https://rocketjobs.pl/sitemaps/part1.xml</loc></sitemap>"
        "</sitemapindex>"
    )
    part0_xml = _index_sitemap_xml("https://rocketjobs.pl/oferty-pracy/job-1")
    part1_xml = _index_sitemap_xml("https://rocketjobs.pl/oferty-pracy/job-2")

    def _fake_get(url: str, **kwargs: Any) -> _FakeResponse:
        if url == ROCKET_JOBS_SITEMAP_URL:
            return _FakeResponse(text=index_xml)
        if url == "https://rocketjobs.pl/sitemaps/part0.xml":
            return _FakeResponse(text=part0_xml)
        if url == "https://rocketjobs.pl/sitemaps/part1.xml":
            return _FakeResponse(text=part1_xml)
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(httpx, "get", _fake_get)

    result = RocketJobsConnector().fetch_sitemap_urls({})

    assert result == [
        "https://rocketjobs.pl/oferty-pracy/job-1",
        "https://rocketjobs.pl/oferty-pracy/job-2",
    ]


def test_fetch_sitemap_urls_returns_none_on_fetch_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(*a: Any, **kw: Any) -> None:
        raise httpx.ConnectError("connection failed")

    monkeypatch.setattr(httpx, "get", _raise)

    assert RocketJobsConnector().fetch_sitemap_urls({}) is None


def test_fetch_sitemap_urls_returns_none_on_malformed_xml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(text="not xml"))

    assert RocketJobsConnector().fetch_sitemap_urls({}) is None


def test_extract_job_posting_json_ld_returns_parsed_dict_for_wellformed_fixture() -> None:
    result = extract_job_posting_json_ld(_JSON_LD_HTML)

    assert result == {
        "@type": "JobPosting",
        "title": "Backend Engineer",
        "url": "https://rocketjobs.pl/oferty-pracy/backend-engineer",
    }


def test_extract_job_posting_json_ld_picks_job_posting_block_among_multiple_ld_json_blocks() -> (
    None
):
    html = (
        '<html><body><script type="application/ld+json">'
        '{"@type": "BreadcrumbList", "itemListElement": []}'
        "</script>"
        '<script type="application/ld+json">'
        '{"@type": "JobPosting", "title": "Backend Engineer"}'
        "</script></body></html>"
    )

    result = extract_job_posting_json_ld(html)

    assert result == {"@type": "JobPosting", "title": "Backend Engineer"}


def test_extract_job_posting_json_ld_returns_none_and_logs_when_no_script_tag_present(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("ERROR", logger="app.connectors.rocket_jobs"):
        result = extract_job_posting_json_ld(
            "<html><body>no ld+json here</body></html>", url="https://x"
        )

    assert result is None
    assert any(
        "Rocket Jobs returned unexpected page shape" in r.getMessage() for r in caplog.records
    )


def test_extract_job_posting_json_ld_returns_none_on_malformed_json_inside_script_tag(
    caplog: pytest.LogCaptureFixture,
) -> None:
    html = '<script type="application/ld+json">{not valid json</script>'

    with caplog.at_level("ERROR", logger="app.connectors.rocket_jobs"):
        result = extract_job_posting_json_ld(html, url="https://x")

    assert result is None
    assert any(
        "Rocket Jobs returned unexpected page shape" in r.getMessage() for r in caplog.records
    )


def test_extract_job_posting_json_ld_skips_malformed_block_and_finds_later_job_posting() -> None:
    html = (
        '<html><body><script type="application/ld+json">{not valid json</script>'
        '<script type="application/ld+json">'
        '{"@type": "JobPosting", "title": "Backend Engineer"}'
        "</script></body></html>"
    )

    result = extract_job_posting_json_ld(html)

    assert result == {"@type": "JobPosting", "title": "Backend Engineer"}


def test_map_rocket_jobs_offer_maps_all_known_fields() -> None:
    result = RocketJobsConnector().map_offer(1, _REAL_JOB_POSTING)

    assert result == {
        "source_id": 1,
        "external_id": "senior-backend-engineer-acme-warszawa",
        "canonical_url": "https://rocketjobs.pl/oferta-pracy/senior-backend-engineer-acme-warszawa",
        "title": "Senior Backend Engineer",
        "company": "Acme",
        "location": "Warszawa",
        "remote": False,
        "seniority": None,
        "salary_min": None,
        "salary_max": None,
        "salary_currency": "PLN",
        "contract_type": "FULL_TIME",
        "posted_at": "2026-06-20T10:00:00+02:00",
        "description": "<p>We are looking for a Senior Backend Engineer.</p>",
    }


def test_map_rocket_jobs_offer_prefers_json_lds_own_url_over_source_url() -> None:
    raw = {
        "title": "Backend Engineer",
        "url": "https://rocketjobs.pl/oferta-pracy/from-json-ld",
        "_source_url": "https://rocketjobs.pl/oferta-pracy/from-fetch",
    }

    result = RocketJobsConnector().map_offer(1, raw)

    assert result["canonical_url"] == "https://rocketjobs.pl/oferta-pracy/from-json-ld"


def test_map_rocket_jobs_offer_falls_back_to_source_url_when_json_ld_has_no_url() -> None:
    raw = {
        "title": "Backend Engineer",
        "_source_url": "https://rocketjobs.pl/oferta-pracy/from-fetch",
    }

    result = RocketJobsConnector().map_offer(1, raw)

    assert result["canonical_url"] == "https://rocketjobs.pl/oferta-pracy/from-fetch"
    assert result["external_id"] == "from-fetch"


def test_map_rocket_jobs_offer_handles_missing_optional_fields() -> None:
    raw = {
        "@type": "JobPosting",
        "title": "Backend Engineer",
        "hiringOrganization": {"@type": "Organization", "name": "Acme"},
    }

    result = RocketJobsConnector().map_offer(1, raw)

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


def test_map_rocket_jobs_offer_maps_telecommute_job_location_type_to_remote() -> None:
    raw = {
        "title": "Backend Engineer",
        "hiringOrganization": {"@type": "Organization", "name": "Acme"},
        "jobLocationType": "TELECOMMUTE",
    }

    result = RocketJobsConnector().map_offer(1, raw)

    assert result["remote"] is True


def test_map_rocket_jobs_offer_handles_completely_unexpected_shape() -> None:
    result = RocketJobsConnector().map_offer(1, {})

    assert result["title"] == ""
    assert result["company"] == ""
    assert result["canonical_url"] is None


def test_map_rocket_jobs_offer_calls_shared_normalize_functions(
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

    monkeypatch.setattr(rocket_jobs, "normalize_remote", _record("normalize_remote"))
    monkeypatch.setattr(rocket_jobs, "normalize_seniority", _record("normalize_seniority"))
    monkeypatch.setattr(rocket_jobs, "normalize_salary", _record("normalize_salary"))

    RocketJobsConnector().map_offer(1, _REAL_JOB_POSTING)

    assert calls["normalize_remote"][0] == ROCKET_JOBS
    assert calls["normalize_seniority"][0] == ROCKET_JOBS
    assert calls["normalize_salary"][0] == ROCKET_JOBS


@pytest.mark.asyncio
async def test_rocket_jobs_run_delegates_to_run_paginated_ingestion_with_sitemap_derived_fetch_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db.models import Source
    from app.ingestion.types import IngestionResult

    monkeypatch.setattr(
        RocketJobsConnector,
        "fetch_sitemap_urls",
        lambda self, config: ["https://x/1", "https://x/2"],
    )

    captured: dict[str, Any] = {}

    async def _fake_run_paginated_ingestion(
        session: Any, source_id: int, **kwargs: Any
    ) -> IngestionResult:
        captured.update(kwargs)
        return IngestionResult(ok=True, fetched=0, created=0)

    monkeypatch.setattr(rocket_jobs, "run_paginated_ingestion", _fake_run_paginated_ingestion)

    connector = RocketJobsConnector()
    source = Source(id=1, connector="rocket_jobs", config_json={})

    await connector.run(None, source)  # type: ignore[arg-type]

    assert captured["page_size"] == 20
    assert captured["max_pages"] == 50
    assert captured["already_seen_stop_threshold"] == 20
    assert callable(captured["fetch_page"])


@pytest.mark.asyncio
async def test_rocket_jobs_run_reads_kwargs_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.db.models import Source
    from app.ingestion.types import IngestionResult

    monkeypatch.setattr(RocketJobsConnector, "fetch_sitemap_urls", lambda self, config: [])

    captured: dict[str, Any] = {}

    async def _fake_run_paginated_ingestion(
        session: Any, source_id: int, **kwargs: Any
    ) -> IngestionResult:
        captured.update(kwargs)
        return IngestionResult(ok=True, fetched=0, created=0)

    monkeypatch.setattr(rocket_jobs, "run_paginated_ingestion", _fake_run_paginated_ingestion)

    connector = RocketJobsConnector()
    source = Source(
        id=1,
        connector="rocket_jobs",
        config_json={"page_size": 5, "max_pages": 3, "already_seen_stop_threshold": 2},
    )

    await connector.run(None, source)  # type: ignore[arg-type]

    assert captured["page_size"] == 5
    assert captured["max_pages"] == 3
    assert captured["already_seen_stop_threshold"] == 2


@pytest.mark.asyncio
async def test_rocket_jobs_run_returns_not_ok_when_sitemap_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db.models import Source
    from app.ingestion.types import IngestionResult

    monkeypatch.setattr(RocketJobsConnector, "fetch_sitemap_urls", lambda self, config: None)

    connector = RocketJobsConnector()
    source = Source(id=1, connector="rocket_jobs", config_json={})

    result = await connector.run(None, source)  # type: ignore[arg-type]

    assert result == IngestionResult(
        ok=False, fetched=0, created=0, error_message="failed to fetch Rocket Jobs offers"
    )


def test_api_rocketjobs_pl_never_referenced_in_connector_module() -> None:
    # Scoped to string literals actually used as URLs (start with "http"), not the whole file
    # text -- the class docstring is expected to *name* api.rocketjobs.pl to document why it's
    # avoided, and that documentation must not trip this assertion.
    tree = ast.parse(inspect.getsource(rocket_jobs))
    url_literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith("http")
    ]

    assert url_literals, "expected at least one URL literal in the module"
    assert all("api.rocketjobs.pl" not in url for url in url_literals)
