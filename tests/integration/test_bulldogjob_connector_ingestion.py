import gzip
import json
from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.connectors.bulldogjob import BULLDOGJOB_SITEMAP_INDEX_URL, BulldogjobConnector
from app.db.models import Offer as OfferModel
from app.db.models import Source
from app.ingestion.types import IngestionResult
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

JOBS_SITEMAP_URL = "https://bulldogjob.com/en/jobs.xml.gz"


class _FakeResponse:
    def __init__(
        self,
        *,
        content: bytes = b"",
        text: str = "",
        status_error: Exception | None = None,
    ) -> None:
        self.content = content
        self.text = text
        self._status_error = status_error

    def raise_for_status(self) -> None:
        if self._status_error is not None:
            raise self._status_error


async def _create_source(
    session: AsyncSession, config_json: dict[str, Any] | None = None
) -> Source:
    source = Source(name=f"bulldogjob-{uuid4()}", config_json=config_json or {})
    session.add(source)
    await session.flush()
    return source


def _gzip_xml(xml_text: str) -> bytes:
    return gzip.compress(xml_text.encode("utf-8"))


def _index_sitemap_xml() -> str:
    return (
        '<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<sitemap><loc>{JOBS_SITEMAP_URL}</loc></sitemap>"
        "</sitemapindex>"
    )


def _jobs_sitemap_xml(urls: list[str]) -> str:
    locs = "".join(f"<url><loc>{url}</loc></url>" for url in urls)
    return (
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{locs}</urlset>"
    )


def _job_url(job_id: str) -> str:
    return f"https://bulldogjob.com/companies/jobs/{job_id}"


def _next_data(job_id: str, position: str, **overrides: Any) -> dict[str, Any]:
    job: dict[str, Any] = {
        "id": job_id,
        "position": position,
        "experienceLevel": "senior",
        "remote": False,
        "publishedAt": "2026-06-15T00:00:00+00:00",
        "offer": None,
        "requirements": "<p>Requirements.</p>",
        "company": {"name": "Acme"},
        "locations": [{"location": {"cityEn": "Warsaw"}}],
        "employmentSalary": None,
        "b2bSalary": {
            "currency": "PLN",
            "minValue": None,
            "maxValue": None,
            "money": "100 - 150",
            "timeframe": "hour",
        },
        "otherSalary": None,
    }
    job.update(overrides)
    return {"props": {"pageProps": {"data": {"job": job}}}}


def _html_for(next_data: dict[str, Any]) -> str:
    return (
        f'<html><body><script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(next_data)}</script></body></html>"
    )


def _detail_html(job_id: str, position: str, **overrides: Any) -> str:
    return _html_for(_next_data(job_id, position, **overrides))


def _unique_job_id(label: str) -> str:
    # Must start with a digit run + "-" to match the real job-URL shape
    # (`_JOB_URL_PATTERN` in app/connectors/bulldogjob.py filters out non-numeric-id sitemap
    # entries such as `/companies/jobs/s/skills,Java`), so `uuid4().hex` (which may start with
    # a letter) can't be used directly here.
    return f"{uuid4().int % 10**8}-{label}"


def _make_router(
    *,
    index_xml: str | None = None,
    jobs_xml: str | None = None,
    detail_html_by_url: dict[str, str] | None = None,
    index_error: Exception | None = None,
    detail_call_log: list[str] | None = None,
) -> Any:
    detail_html_by_url = detail_html_by_url or {}

    def _router(url: str, **kwargs: Any) -> _FakeResponse:
        if url == BULLDOGJOB_SITEMAP_INDEX_URL:
            if index_error is not None:
                raise index_error
            return _FakeResponse(content=_gzip_xml(index_xml or _index_sitemap_xml()))
        if url == JOBS_SITEMAP_URL:
            return _FakeResponse(content=_gzip_xml(jobs_xml or _jobs_sitemap_xml([])))
        if detail_call_log is not None:
            detail_call_log.append(url)
        if url in detail_html_by_url:
            return _FakeResponse(text=detail_html_by_url[url])
        return _FakeResponse(status_error=httpx.ConnectError("not found"))

    return _router


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_bulldogjob_ingestion_persists_and_maps_offers(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    id1, id2 = _unique_job_id("backend"), _unique_job_id("frontend")
    url1, url2 = _job_url(id1), _job_url(id2)
    next_data1 = _next_data(id1, "Backend Engineer")
    next_data2 = _next_data(id2, "Frontend Engineer")

    monkeypatch.setattr(
        httpx,
        "get",
        _make_router(
            jobs_xml=_jobs_sitemap_xml([url1, url2]),
            detail_html_by_url={url1: _html_for(next_data1), url2: _html_for(next_data2)},
        ),
    )

    result = await BulldogjobConnector().run(db_session, source)
    await db_session.commit()

    assert result == IngestionResult(ok=True, fetched=2, created=2)
    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 2
    titles = {row.title for row in rows}
    assert titles == {"Backend Engineer", "Frontend Engineer"}
    row1 = next(r for r in rows if r.title == "Backend Engineer")
    assert row1.raw_payload == next_data1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_bulldogjob_ingestion_returns_not_ok_on_sitemap_fetch_failure(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    monkeypatch.setattr(
        httpx, "get", _make_router(index_error=httpx.ConnectError("connection failed"))
    )

    result = await BulldogjobConnector().run(db_session, source)
    await db_session.commit()

    assert result == IngestionResult(
        ok=False, fetched=0, created=0, error_message="failed to fetch Bulldogjob offers"
    )
    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_bulldogjob_ingestion_skips_single_broken_detail_page_without_failing_run(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    good_id, broken_id = _unique_job_id("good"), _unique_job_id("broken")
    good_url, broken_url = _job_url(good_id), _job_url(broken_id)
    good_html = _detail_html(good_id, "Backend Engineer")

    monkeypatch.setattr(
        httpx,
        "get",
        _make_router(
            jobs_xml=_jobs_sitemap_xml([good_url, broken_url]),
            detail_html_by_url={good_url: good_html},
        ),
    )

    result = await BulldogjobConnector().run(db_session, source)
    await db_session.commit()

    assert result.ok is True
    assert result.created == 1
    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].title == "Backend Engineer"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_bulldogjob_ingestion_dedups_on_reingest(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    job_id = _unique_job_id("backend")
    url = _job_url(job_id)
    html = _detail_html(job_id, "Backend Engineer")

    monkeypatch.setattr(
        httpx,
        "get",
        _make_router(jobs_xml=_jobs_sitemap_xml([url]), detail_html_by_url={url: html}),
    )

    first = await BulldogjobConnector().run(db_session, source)
    await db_session.commit()
    second = await BulldogjobConnector().run(db_session, source)
    await db_session.commit()

    assert first.created == 1
    assert second.created == 0
    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_bulldogjob_ingestion_already_seen_stop_threshold_avoids_refetching_every_url(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(
        db_session, config_json={"page_size": 5, "already_seen_stop_threshold": 3}
    )
    ids = [_unique_job_id(f"job{i}") for i in range(10)]
    urls = [_job_url(job_id) for job_id in ids]
    htmls = {_job_url(job_id): _detail_html(job_id, f"Job {i}") for i, job_id in enumerate(ids)}

    call_log_1: list[str] = []
    monkeypatch.setattr(
        httpx,
        "get",
        _make_router(
            jobs_xml=_jobs_sitemap_xml(urls),
            detail_html_by_url=htmls,
            detail_call_log=call_log_1,
        ),
    )
    first = await BulldogjobConnector().run(db_session, source)
    await db_session.commit()
    assert first.created == 10
    assert len(call_log_1) == 10

    call_log_2: list[str] = []
    monkeypatch.setattr(
        httpx,
        "get",
        _make_router(
            jobs_xml=_jobs_sitemap_xml(urls),
            detail_html_by_url=htmls,
            detail_call_log=call_log_2,
        ),
    )
    second = await BulldogjobConnector().run(db_session, source)
    await db_session.commit()

    assert second.created == 0
    assert len(call_log_2) < len(urls)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_bulldogjob_ingestion_range_mode_skips_offers_outside_since_until(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Bulldogjob's `publishedAt` is an ISO string (unlike NoFluffJobs's epoch-ms `posted`) --
    # exercises that shape through the shared fetch-range filter.
    source = await _create_source(
        db_session,
        config_json={
            "fetch_range": {
                "mode": "range",
                "since": "2026-06-01T00:00:00Z",
                "until": "2026-06-30T00:00:00Z",
            }
        },
    )
    in_id, out_id = _unique_job_id("in-range"), _unique_job_id("out-range")
    in_range_url, out_of_range_url = _job_url(in_id), _job_url(out_id)

    in_range_html = _detail_html(in_id, "In Range", publishedAt="2026-06-15T00:00:00Z")
    out_of_range_html = _detail_html(out_id, "Out Of Range", publishedAt="2026-05-01T00:00:00Z")

    monkeypatch.setattr(
        httpx,
        "get",
        _make_router(
            jobs_xml=_jobs_sitemap_xml([in_range_url, out_of_range_url]),
            detail_html_by_url={in_range_url: in_range_html, out_of_range_url: out_of_range_html},
        ),
    )

    result = await BulldogjobConnector().run(db_session, source)
    await db_session.commit()

    assert result.fetched == 2
    assert result.created == 1
    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].title == "In Range"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_bulldogjob_ingestion_resumes_from_persisted_cursor_across_runs(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # BUG41 regression: `max_pages=1` forces a single run to only cover the sitemap's first
    # `page_size` URLs, mirroring the real Bulldogjob config (~1000-URL sitemap needing many
    # scheduled runs to fully walk). Before the fix, every run restarted at cursor 0 and never
    # made it past this same first slice.
    source = await _create_source(db_session, config_json={"page_size": 5, "max_pages": 1})
    ids = [_unique_job_id(f"job{i}") for i in range(10)]
    urls = [_job_url(job_id) for job_id in ids]
    htmls = {_job_url(job_id): _detail_html(job_id, f"Job {i}") for i, job_id in enumerate(ids)}

    call_log_1: list[str] = []
    monkeypatch.setattr(
        httpx,
        "get",
        _make_router(
            jobs_xml=_jobs_sitemap_xml(urls), detail_html_by_url=htmls, detail_call_log=call_log_1
        ),
    )
    first = await BulldogjobConnector().run(db_session, source)
    await db_session.commit()

    assert first.created == 5
    assert call_log_1 == urls[:5]
    assert source.config_json["sitemap_cursor"] == 5

    call_log_2: list[str] = []
    monkeypatch.setattr(
        httpx,
        "get",
        _make_router(
            jobs_xml=_jobs_sitemap_xml(urls), detail_html_by_url=htmls, detail_call_log=call_log_2
        ),
    )
    second = await BulldogjobConnector().run(db_session, source)
    await db_session.commit()

    assert second.created == 5
    assert call_log_2 == urls[5:]
    assert source.config_json["sitemap_cursor"] == 0

    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 10


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_bulldogjob_ingestion_since_cutoff_does_not_stop_pagination_early(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # BUG41's exact Bulldogjob failure mode: sitemap order isn't recency-sorted, so an old
    # listing landing on page 1 (page_size=1 forces separate pages) must not be mistaken for
    # "the rest of the catalog is old too" and truncate pagination before page 2 is fetched.
    source = await _create_source(
        db_session,
        config_json={
            "page_size": 1,
            "max_pages": 5,
            "fetch_range": {"mode": "range", "since": "2026-06-01T00:00:00Z"},
        },
    )
    old_id, new_id = _unique_job_id("old"), _unique_job_id("new")
    old_url, new_url = _job_url(old_id), _job_url(new_id)
    old_html = _detail_html(old_id, "Old Listing", publishedAt="2026-01-01T00:00:00Z")
    new_html = _detail_html(new_id, "New Listing", publishedAt="2026-06-15T00:00:00Z")

    monkeypatch.setattr(
        httpx,
        "get",
        _make_router(
            jobs_xml=_jobs_sitemap_xml([old_url, new_url]),
            detail_html_by_url={old_url: old_html, new_url: new_html},
        ),
    )

    result = await BulldogjobConnector().run(db_session, source)
    await db_session.commit()

    assert result.fetched == 2
    assert result.created == 1
    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].title == "New Listing"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_bulldogjob_ingestion_uses_page_size_from_config(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session, config_json={"page_size": 5})
    ids = [_unique_job_id(f"job{i}") for i in range(8)]
    urls = [_job_url(job_id) for job_id in ids]
    htmls = {_job_url(job_id): _detail_html(job_id, f"Job {i}") for i, job_id in enumerate(ids)}

    call_log: list[str] = []
    monkeypatch.setattr(
        httpx,
        "get",
        _make_router(
            jobs_xml=_jobs_sitemap_xml(urls), detail_html_by_url=htmls, detail_call_log=call_log
        ),
    )

    await BulldogjobConnector().run(db_session, source)
    await db_session.commit()

    assert len(call_log) == 8
