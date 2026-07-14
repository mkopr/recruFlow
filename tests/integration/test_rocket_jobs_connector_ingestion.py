import json
from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.connectors.rocket_jobs import ROCKET_JOBS_SITEMAP_URL, RocketJobsConnector
from app.db.models import MatchScore as MatchScoreModel
from app.db.models import Offer as OfferModel
from app.db.models import Source
from app.ingestion.normalize import ROCKET_JOBS
from app.ingestion.types import IngestionResult
from app.llm.matcher import _MatcherOutput
from app.scoring.batch import run_batch_scoring
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_batch_scoring import _create_profile, _delete_sources_and_dependents
from tests.integration.test_langchain_matcher_batch import _STRONG_OUTPUT_KWARGS, _FakeChain
from tests.integration.test_offers_routes import _deactivate_all_profiles


class _FakeResponse:
    def __init__(
        self,
        *,
        text: str = "",
        status_error: Exception | None = None,
    ) -> None:
        self.text = text
        self._status_error = status_error

    def raise_for_status(self) -> None:
        if self._status_error is not None:
            raise self._status_error


async def _create_source(
    session: AsyncSession, config_json: dict[str, Any] | None = None, connector: str | None = None
) -> Source:
    source = Source(
        name=f"rocket-jobs-{uuid4()}", connector=connector, config_json=config_json or {}
    )
    session.add(source)
    await session.flush()
    return source


def _urlset_xml(urls: list[str]) -> str:
    locs = "".join(f"<url><loc>{url}</loc></url>" for url in urls)
    return (
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{locs}</urlset>"
    )


def _job_url(slug: str) -> str:
    return f"https://rocketjobs.pl/oferta-pracy/{slug}"


def _job_posting(slug: str, title: str, **overrides: Any) -> dict[str, Any]:
    # No "url" key, matching real Rocket Jobs JSON-LD confirmed live 2026-07-14 (see
    # docs/adr/0025-rocket-jobs-sitemap-and-json-ld-investigation.md) -- canonical_url is
    # expected to come from the "_source_url" the connector's own `run` injects instead.
    posting: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": title,
        "description": "<p>Job description.</p>",
        "datePosted": "2026-06-15T00:00:00+00:00",
        "employmentType": "FULL_TIME",
        "hiringOrganization": {"@type": "Organization", "name": "Acme"},
        "jobLocation": {
            "@type": "Place",
            "address": {"@type": "PostalAddress", "addressLocality": "Warszawa"},
        },
    }
    posting.update(overrides)
    return posting


def _html_for(job_posting: dict[str, Any]) -> str:
    return (
        '<html><body><script type="application/ld+json">'
        f"{json.dumps(job_posting)}"
        "</script></body></html>"
    )


def _detail_html(slug: str, title: str, **overrides: Any) -> str:
    return _html_for(_job_posting(slug, title, **overrides))


def _unique_slug(label: str) -> str:
    return f"{label}-{uuid4().hex[:8]}"


def _make_router(
    *,
    sitemap_xml: str | None = None,
    detail_html_by_url: dict[str, str] | None = None,
    sitemap_error: Exception | None = None,
    detail_call_log: list[str] | None = None,
) -> Any:
    detail_html_by_url = detail_html_by_url or {}

    def _router(url: str, **kwargs: Any) -> _FakeResponse:
        if url == ROCKET_JOBS_SITEMAP_URL:
            if sitemap_error is not None:
                raise sitemap_error
            return _FakeResponse(text=sitemap_xml or _urlset_xml([]))
        if detail_call_log is not None:
            detail_call_log.append(url)
        if url in detail_html_by_url:
            return _FakeResponse(text=detail_html_by_url[url])
        return _FakeResponse(status_error=httpx.ConnectError("not found"))

    return _router


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_rocket_jobs_ingestion_persists_and_maps_offers(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    slug1, slug2 = _unique_slug("backend"), _unique_slug("frontend")
    url1, url2 = _job_url(slug1), _job_url(slug2)
    posting1 = _job_posting(slug1, "Backend Engineer")
    posting2 = _job_posting(slug2, "Frontend Engineer")

    monkeypatch.setattr(
        httpx,
        "get",
        _make_router(
            sitemap_xml=_urlset_xml([url1, url2]),
            detail_html_by_url={url1: _html_for(posting1), url2: _html_for(posting2)},
        ),
    )

    result = await RocketJobsConnector().run(db_session, source)
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
    assert row1.raw_payload == {**posting1, "_source_url": url1}
    assert row1.canonical_url == url1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_rocket_jobs_ingestion_returns_not_ok_on_sitemap_fetch_failure(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    monkeypatch.setattr(
        httpx, "get", _make_router(sitemap_error=httpx.ConnectError("connection failed"))
    )

    result = await RocketJobsConnector().run(db_session, source)
    await db_session.commit()

    assert result == IngestionResult(
        ok=False, fetched=0, created=0, error_message="failed to fetch Rocket Jobs offers"
    )
    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_rocket_jobs_ingestion_skips_single_broken_detail_page_without_failing_run(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    good_slug, broken_slug = _unique_slug("good"), _unique_slug("broken")
    good_url, broken_url = _job_url(good_slug), _job_url(broken_slug)
    good_html = _detail_html(good_slug, "Backend Engineer")

    monkeypatch.setattr(
        httpx,
        "get",
        _make_router(
            sitemap_xml=_urlset_xml([good_url, broken_url]),
            detail_html_by_url={good_url: good_html},
        ),
    )

    result = await RocketJobsConnector().run(db_session, source)
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
async def test_run_rocket_jobs_ingestion_dedups_on_reingest(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    slug = _unique_slug("backend")
    url = _job_url(slug)
    html = _detail_html(slug, "Backend Engineer")

    monkeypatch.setattr(
        httpx,
        "get",
        _make_router(sitemap_xml=_urlset_xml([url]), detail_html_by_url={url: html}),
    )

    first = await RocketJobsConnector().run(db_session, source)
    await db_session.commit()
    second = await RocketJobsConnector().run(db_session, source)
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
async def test_run_rocket_jobs_ingestion_already_seen_stop_threshold_avoids_refetching_every_url(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(
        db_session, config_json={"page_size": 5, "already_seen_stop_threshold": 3}
    )
    slugs = [_unique_slug(f"job{i}") for i in range(10)]
    urls = [_job_url(slug) for slug in slugs]
    htmls = {_job_url(slug): _detail_html(slug, f"Job {i}") for i, slug in enumerate(slugs)}

    call_log_1: list[str] = []
    monkeypatch.setattr(
        httpx,
        "get",
        _make_router(
            sitemap_xml=_urlset_xml(urls), detail_html_by_url=htmls, detail_call_log=call_log_1
        ),
    )
    first = await RocketJobsConnector().run(db_session, source)
    await db_session.commit()
    assert first.created == 10
    assert len(call_log_1) == 10

    call_log_2: list[str] = []
    monkeypatch.setattr(
        httpx,
        "get",
        _make_router(
            sitemap_xml=_urlset_xml(urls), detail_html_by_url=htmls, detail_call_log=call_log_2
        ),
    )
    second = await RocketJobsConnector().run(db_session, source)
    await db_session.commit()

    assert second.created == 0
    assert len(call_log_2) < len(urls)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_rocket_jobs_ingestion_uses_page_size_from_config(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session, config_json={"page_size": 5})
    slugs = [_unique_slug(f"job{i}") for i in range(8)]
    urls = [_job_url(slug) for slug in slugs]
    htmls = {_job_url(slug): _detail_html(slug, f"Job {i}") for i, slug in enumerate(slugs)}

    call_log: list[str] = []
    monkeypatch.setattr(
        httpx,
        "get",
        _make_router(
            sitemap_xml=_urlset_xml(urls), detail_html_by_url=htmls, detail_call_log=call_log
        ),
    )

    await RocketJobsConnector().run(db_session, source)
    await db_session.commit()

    assert len(call_log) == 8


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_rocket_jobs_ingestion_scoring_eligibility(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session, connector=ROCKET_JOBS)
    slug = _unique_slug("backend")
    url = _job_url(slug)
    html = _detail_html(slug, "Backend Engineer")

    monkeypatch.setattr(
        httpx,
        "get",
        _make_router(sitemap_xml=_urlset_xml([url]), detail_html_by_url={url: html}),
    )

    try:
        ingestion_result = await RocketJobsConnector().run(db_session, source)
        await db_session.commit()
        assert ingestion_result.created == 1

        await _deactivate_all_profiles(db_session)
        profile = await _create_profile(db_session)
        await db_session.commit()

        summary = await run_batch_scoring(
            db_session,
            connectors={ROCKET_JOBS},
            chain_factory=lambda: _FakeChain(_MatcherOutput(**_STRONG_OUTPUT_KWARGS)),
        )
        await db_session.commit()

        assert summary.scored == 1
        assert summary.failed == 0

        rows = (
            (
                await db_session.execute(
                    select(MatchScoreModel).where(MatchScoreModel.profile_id == profile.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
    finally:
        await _delete_sources_and_dependents(db_session, [source.id])
