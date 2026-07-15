import json
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from app.connectors import pracuj
from app.connectors.pracuj import PracujConnector
from app.db.models import IngestionFailure, Source
from app.db.models import MatchScore as MatchScoreModel
from app.db.models import Offer as OfferModel
from app.ingestion.normalize import PRACUJ
from app.ingestion.types import IngestionResult
from app.llm.matcher import _MatcherOutput
from app.scoring.batch import run_batch_scoring
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_batch_scoring import _create_profile, _delete_sources_and_dependents
from tests.integration.test_langchain_matcher_batch import _STRONG_OUTPUT_KWARGS, _FakeChain
from tests.integration.test_offers_routes import _deactivate_all_profiles


class _FakeResponse:
    def __init__(self, *, text: str = "", status: int = 200) -> None:
        self._text = text
        self.status = status
        self.headers: dict[str, str] = {}

    async def text(self) -> str:
        return self._text


Router = Callable[[str], "_FakeResponse | None"]


class _FakePage:
    def __init__(self, router: Router) -> None:
        self._router = router

    async def goto(
        self, url: str, timeout: float | None = None, wait_until: str | None = None
    ) -> Any:
        return self._router(url)


class _FakeContext:
    def __init__(self, router: Router) -> None:
        self._router = router

    async def new_page(self) -> _FakePage:
        return _FakePage(self._router)

    async def close(self) -> None:
        return None


class _FakeBrowser:
    def __init__(self, router: Router) -> None:
        self._router = router

    async def new_context(self, **kwargs: Any) -> _FakeContext:
        return _FakeContext(self._router)

    async def close(self) -> None:
        return None


class _FakeChromium:
    def __init__(self, router: Router) -> None:
        self._router = router

    async def launch(self, **kwargs: Any) -> _FakeBrowser:
        return _FakeBrowser(self._router)


class _FakePlaywright:
    def __init__(self, router: Router) -> None:
        self.chromium = _FakeChromium(router)


class _FakePlaywrightContextManager:
    def __init__(self, router: Router) -> None:
        self._router = router

    async def __aenter__(self) -> _FakePlaywright:
        return _FakePlaywright(self._router)

    async def __aexit__(self, *exc: Any) -> bool:
        return False


def _install_router(monkeypatch: pytest.MonkeyPatch, router: Router) -> None:
    monkeypatch.setattr(pracuj, "async_playwright", lambda: _FakePlaywrightContextManager(router))


async def _create_source(
    session: AsyncSession, config_json: dict[str, Any] | None = None, connector: str | None = None
) -> Source:
    source = Source(name=f"pracuj-{uuid4()}", connector=connector, config_json=config_json or {})
    session.add(source)
    await session.flush()
    return source


def _next_data_html(query_key: list[Any], data: Any) -> str:
    next_data = {
        "props": {
            "pageProps": {
                "dehydratedState": {"queries": [{"queryKey": query_key, "state": {"data": data}}]}
            }
        }
    }
    return (
        '<html><body><script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(next_data)}</script></body></html>"
    )


def _listing_html(grouped_offers: list[dict[str, Any]]) -> str:
    return _next_data_html(
        ["jobOffers", {"pn": 1, "rop": 10}, "Default", True, "pl"],
        {"groupedOffers": grouped_offers, "offersTotalCount": len(grouped_offers)},
    )


def _detail_record(job_offer_web_id: int, title: str, url: str, **overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "jobOfferWebId": job_offer_web_id,
        "publicationDetails": {"dateOfInitialPublicationUtc": "2026-06-15T00:00:00Z"},
        "attributes": {
            "jobTitle": title,
            "description": "Job description.",
            "offerAbsoluteUrl": url,
            "displayEmployerName": "Acme",
            "workplaces": [{"displayAddress": "Warszawa"}],
            "employment": {
                "positionLevels": [{"pracujPlName": "specjalista / specjalistka (mid / regular)"}],
                "entirelyRemoteWork": False,
                "typesOfContracts": [
                    {
                        "pracujPlName": "umowa o pracę",
                        "salary": {
                            "from": 8000,
                            "to": 10000,
                            "currency": {"code": "PLN"},
                            "timeUnit": {"id": 0},
                            "salaryKind": {"code": "gross"},
                        },
                    }
                ],
                "workModes": [{"code": "hybrid", "name": "praca hybrydowa"}],
            },
        },
    }
    record["attributes"].update(overrides)
    return record


def _detail_html(record: dict[str, Any]) -> str:
    return _next_data_html(["jobOffer", str(record["jobOfferWebId"]), "pl"], record)


def _group(*, offer_url: str) -> dict[str, Any]:
    return {"groupId": "g1", "jobTitle": "placeholder", "offers": [{"offerAbsoluteUri": offer_url}]}


def _job_url(slug: str) -> str:
    return f"https://www.pracuj.pl/praca/{slug},oferta,{abs(hash(slug)) % 10**7}"


def _unique_slug(label: str) -> str:
    return f"{label}-{uuid4().hex[:8]}"


def _make_router(
    *,
    listing_url: str,
    grouped_offers: list[dict[str, Any]],
    detail_records_by_url: dict[str, dict[str, Any]] | None = None,
    detail_status_by_url: dict[str, int] | None = None,
    detail_call_log: list[str] | None = None,
) -> Router:
    detail_records_by_url = detail_records_by_url or {}
    detail_status_by_url = detail_status_by_url or {}

    def _router(url: str) -> _FakeResponse | None:
        if url == listing_url:
            return _FakeResponse(text=_listing_html(grouped_offers))
        if detail_call_log is not None:
            detail_call_log.append(url)
        if url in detail_status_by_url:
            return _FakeResponse(
                text="<html>Just a moment...</html>", status=detail_status_by_url[url]
            )
        if url in detail_records_by_url:
            return _FakeResponse(text=_detail_html(detail_records_by_url[url]))
        return None

    return _router


def _listing_url(category_filter: str, *, page: int = 1, rop: int = 10) -> str:
    from urllib.parse import quote

    return f"https://www.pracuj.pl/praca/{quote(category_filter, safe='')};kw?pn={page}&rop={rop}"


# rate_limit_delay_seconds=0 keeps this suite fast -- same precedent as
# test_justjoinit_connector_ingestion.py -- since the connector's own default (4.0s,
# deliberately conservative for real browser-driven fetching) would otherwise make every test
# in this file sleep for real between fetches.
_FAST_IT_CONFIG: dict[str, Any] = {"category_filter": "it", "rate_limit_delay_seconds": 0}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_pracuj_ingestion_creates_offers_with_raw_payload_stored(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session, config_json=_FAST_IT_CONFIG)
    slug1, slug2 = _unique_slug("backend"), _unique_slug("frontend")
    url1, url2 = _job_url(slug1), _job_url(slug2)
    record1 = _detail_record(1001, "Backend Engineer", url1)
    record2 = _detail_record(1002, "Frontend Engineer", url2)

    _install_router(
        monkeypatch,
        _make_router(
            listing_url=_listing_url("it"),
            grouped_offers=[_group(offer_url=url1), _group(offer_url=url2)],
            detail_records_by_url={url1: record1, url2: record2},
        ),
    )

    result = await PracujConnector().run(db_session, source)
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
    assert row1.raw_payload == record1
    assert row1.canonical_url == url1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_pracuj_ingestion_dedups_on_reingest(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session, config_json=_FAST_IT_CONFIG)
    slug = _unique_slug("backend")
    url = _job_url(slug)
    record = _detail_record(2001, "Backend Engineer", url)

    _install_router(
        monkeypatch,
        _make_router(
            listing_url=_listing_url("it"),
            grouped_offers=[_group(offer_url=url)],
            detail_records_by_url={url: record},
        ),
    )

    first = await PracujConnector().run(db_session, source)
    await db_session.commit()

    _install_router(
        monkeypatch,
        _make_router(
            listing_url=_listing_url("it"),
            grouped_offers=[_group(offer_url=url)],
            detail_records_by_url={url: record},
        ),
    )
    second = await PracujConnector().run(db_session, source)
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
async def test_run_pracuj_ingestion_applies_category_filter_end_to_end(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session, config_json=_FAST_IT_CONFIG)
    it_slug, sales_slug = _unique_slug("it-job"), _unique_slug("sales-job")
    it_url, sales_url = _job_url(it_slug), _job_url(sales_slug)
    it_record = _detail_record(3001, "Python Developer", it_url)

    # The "it" listing URL only ever yields the IT offer -- Pracuj.pl's own server performs the
    # keyword match, so a router that would answer a *different* keyword's listing URL with the
    # sales offer (never installed here) proves the configured filter, not local post-filtering,
    # determined which offer was even enumerable.
    _install_router(
        monkeypatch,
        _make_router(
            listing_url=_listing_url("it"),
            grouped_offers=[_group(offer_url=it_url)],
            detail_records_by_url={it_url: it_record},
        ),
    )

    result = await PracujConnector().run(db_session, source)
    await db_session.commit()

    assert result.created == 1
    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].title == "Python Developer"
    assert sales_url != it_url  # sanity: distinct fixture URLs, sales offer never fetched


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_pracuj_ingestion_resumes_from_persisted_listing_page_cursor(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # BUG42 regression: enumeration must resume from the previous run's listing page instead
    # of restarting at page 1 every time -- same class of gap BUG41 fixed for Rocket
    # Jobs/Bulldogjob's sitemap enumeration. `page_size=1, max_pages=1` forces each run to
    # cover exactly one listing page, so a second run only succeeds if it actually asks for
    # page 2 -- the fixture router below only answers page 2's URL, not page 1's.
    source = await _create_source(
        db_session,
        config_json={
            "category_filter": "it",
            "rate_limit_delay_seconds": 0,
            "page_size": 1,
            "max_pages": 1,
        },
    )
    slug1, slug2 = _unique_slug("page1"), _unique_slug("page2")
    url1, url2 = _job_url(slug1), _job_url(slug2)
    record1 = _detail_record(6001, "Page One Engineer", url1)
    record2 = _detail_record(6002, "Page Two Engineer", url2)

    _install_router(
        monkeypatch,
        _make_router(
            listing_url=_listing_url("it", page=1, rop=1),
            grouped_offers=[_group(offer_url=url1)],
            detail_records_by_url={url1: record1},
        ),
    )
    first = await PracujConnector().run(db_session, source)
    await db_session.commit()

    assert first.created == 1
    assert source.config_json["listing_page_cursor"] == 2

    _install_router(
        monkeypatch,
        _make_router(
            listing_url=_listing_url("it", page=2, rop=1),
            grouped_offers=[_group(offer_url=url2)],
            detail_records_by_url={url2: record2},
        ),
    )
    second = await PracujConnector().run(db_session, source)
    await db_session.commit()

    assert second.created == 1
    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 2
    titles = {row.title for row in rows}
    assert titles == {"Page One Engineer", "Page Two Engineer"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pracuj_connector_failure_recorded_not_swallowed(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session, config_json=_FAST_IT_CONFIG)
    ok_slug, challenge_slug = _unique_slug("ok"), _unique_slug("challenge")
    ok_url, challenge_url = _job_url(ok_slug), _job_url(challenge_slug)
    ok_record = _detail_record(4001, "Backend Engineer", ok_url)

    _install_router(
        monkeypatch,
        _make_router(
            listing_url=_listing_url("it"),
            grouped_offers=[_group(offer_url=ok_url), _group(offer_url=challenge_url)],
            detail_records_by_url={ok_url: ok_record},
            detail_status_by_url={challenge_url: 403},
        ),
    )

    result = await PracujConnector().run(db_session, source)
    await db_session.commit()

    failures = (
        (
            await db_session.execute(
                select(IngestionFailure).where(IngestionFailure.source_id == source.id)
            )
        )
        .scalars()
        .all()
    )
    assert not (result.ok is True and result.created == 0 and not failures), (
        "connector must not silently report zero offers on a mid-run challenge page"
    )
    assert len(failures) == 1
    assert failures[0].status == "open"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pracuj_offer_becomes_scoring_eligible(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session, connector=PRACUJ, config_json=_FAST_IT_CONFIG)
    slug = _unique_slug("backend")
    url = _job_url(slug)
    record = _detail_record(5001, "Backend Engineer", url)

    _install_router(
        monkeypatch,
        _make_router(
            listing_url=_listing_url("it"),
            grouped_offers=[_group(offer_url=url)],
            detail_records_by_url={url: record},
        ),
    )

    try:
        ingestion_result = await PracujConnector().run(db_session, source)
        await db_session.commit()
        assert ingestion_result.created == 1

        await _deactivate_all_profiles(db_session)
        profile = await _create_profile(db_session)
        await db_session.commit()

        summary = await run_batch_scoring(
            db_session,
            connectors={PRACUJ},
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
