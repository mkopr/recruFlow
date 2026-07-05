from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.connectors.solid_jobs import run_solid_jobs_ingestion
from app.db.models import Offer as OfferModel
from app.db.models import Source
from app.ingestion.types import IngestionResult
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class _FakeResponse:
    def __init__(
        self,
        *,
        json_data: Any = None,
        text: str = "",
        status_error: Exception | None = None,
    ) -> None:
        self._json_data = json_data
        self.text = text
        self._status_error = status_error

    def raise_for_status(self) -> None:
        if self._status_error is not None:
            raise self._status_error

    def json(self) -> Any:
        return self._json_data


async def _create_source(
    session: AsyncSession, config_json: dict[str, Any] | None = None
) -> Source:
    source = Source(name=f"solid-jobs-{uuid4()}", config_json=config_json or {})
    session.add(source)
    await session.flush()
    return source


def _unique_url(path: str) -> str:
    return f"https://solid.jobs/o/{uuid4()}/{path}"


def _raw_offer(**overrides: Any) -> dict[str, Any]:
    offer = {
        "jobOfferKey": str(uuid4()),
        "url": _unique_url("x"),
        "title": "Backend Engineer",
        "company": "Acme",
        "locations": ["Warszawa"],
        "isRemote": True,
        "isHybrid": False,
        "experienceLevel": "Senior",
        "salary": {"from": 18000, "to": 24000, "currency": "PLN", "employmentType": "b2b"},
        "validFrom": "2026-06-01T00:00:00Z",
        "description": "great role",
    }
    offer.update(overrides)
    return offer


def _page_payload(offers: list[dict[str, Any]], *, page_size: int = 100) -> dict[str, Any]:
    return {
        "jobs": offers,
        "pageIndex": 0,
        "pageSize": page_size,
        "totalCount": len(offers),
        "totalPages": 1,
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_solid_jobs_ingestion_persists_and_maps_offers(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    offer = _raw_offer()
    monkeypatch.setattr(
        httpx, "get", lambda *a, **kw: _FakeResponse(json_data=_page_payload([offer]))
    )

    result = await run_solid_jobs_ingestion(db_session, source, campaign="recruflow")
    await db_session.commit()

    assert result.ok is True
    assert result.fetched == 1
    assert result.created == 1
    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].title == "Backend Engineer"
    assert rows[0].raw_payload == offer


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_solid_jobs_ingestion_handles_zero_offers(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(json_data=_page_payload([])))

    result = await run_solid_jobs_ingestion(db_session, source, campaign="recruflow")
    await db_session.commit()

    assert result == IngestionResult(ok=True, fetched=0, created=0)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_solid_jobs_ingestion_returns_not_ok_on_transport_failure(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)

    def _raise(*a: Any, **kw: Any) -> None:
        raise httpx.ConnectError("connection failed")

    monkeypatch.setattr(httpx, "get", _raise)

    result = await run_solid_jobs_ingestion(db_session, source, campaign="recruflow")
    await db_session.commit()

    assert result == IngestionResult(
        ok=False, fetched=0, created=0, error_message="failed to fetch SOLID.Jobs offers"
    )
    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_solid_jobs_ingestion_returns_not_ok_on_unexpected_shape(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    monkeypatch.setattr(
        httpx, "get", lambda *a, **kw: _FakeResponse(json_data={"unexpected": "shape"})
    )

    result = await run_solid_jobs_ingestion(db_session, source, campaign="recruflow")
    await db_session.commit()

    assert result.ok is False
    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_solid_jobs_ingestion_skips_invalid_offer_without_crashing(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    valid_offer = _raw_offer()
    invalid_offer = _raw_offer(title="")
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _FakeResponse(json_data=_page_payload([valid_offer, invalid_offer])),
    )

    result = await run_solid_jobs_ingestion(db_session, source, campaign="recruflow")
    await db_session.commit()

    assert result.ok is True
    assert result.fetched == 2
    assert result.created == 1
    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_solid_jobs_ingestion_dedups_on_reingest(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    offer = _raw_offer()
    monkeypatch.setattr(
        httpx, "get", lambda *a, **kw: _FakeResponse(json_data=_page_payload([offer]))
    )

    first = await run_solid_jobs_ingestion(db_session, source, campaign="recruflow")
    await db_session.commit()
    second = await run_solid_jobs_ingestion(db_session, source, campaign="recruflow")
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
async def test_run_solid_jobs_ingestion_sets_campaign_query_param_on_every_page_request(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session, config_json={"page_size": 1})
    captured: list[dict[str, Any]] = []

    def _fake_get(url: str, *, params: dict[str, Any], **kw: Any) -> _FakeResponse:
        captured.append(params)
        page_index = params["pageIndex"]
        if page_index == 0:
            return _FakeResponse(json_data=_page_payload([_raw_offer()], page_size=1))
        return _FakeResponse(json_data=_page_payload([], page_size=1))

    monkeypatch.setattr(httpx, "get", _fake_get)

    await run_solid_jobs_ingestion(db_session, source, campaign="recruflow")
    await db_session.commit()

    assert len(captured) >= 1
    for params in captured:
        assert params["campaign"] == "recruflow"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_solid_jobs_ingestion_applies_division_cities_salary_experience_terms_from_config(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(
        db_session,
        config_json={
            "division": "IT",
            "cities": ["Warsaw"],
            "min_salary": 15000,
            "experience_levels": ["Senior"],
            "terms": ["python"],
        },
    )
    captured: dict[str, Any] = {}

    def _fake_get(url: str, *, params: dict[str, Any], **kw: Any) -> _FakeResponse:
        captured["url"] = url
        captured["params"] = params
        return _FakeResponse(json_data=_page_payload([]))

    monkeypatch.setattr(httpx, "get", _fake_get)

    await run_solid_jobs_ingestion(db_session, source, campaign="recruflow")
    await db_session.commit()

    assert captured["url"] == "https://solid.jobs/public-api/offers/IT"
    assert captured["params"]["search.cities"] == "Warsaw"
    assert captured["params"]["search.minimumSalary"] == 15000
    assert captured["params"]["search.experiences"] == "Senior"
    assert captured["params"]["search.searchTerm"] == "python"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_solid_jobs_ingestion_stops_pagination_after_consecutive_already_seen(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Pre-seed two offers that page 1 will re-report, so page 1 is entirely already-seen.
    # With already_seen_stop_threshold=2 this must stop before a third page is requested.
    source = await _create_source(
        db_session,
        config_json={"page_size": 2, "already_seen_stop_threshold": 2},
    )
    already_seen_offers = [_raw_offer(), _raw_offer()]
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _FakeResponse(json_data=_page_payload(already_seen_offers, page_size=2)),
    )
    await run_solid_jobs_ingestion(db_session, source, campaign="recruflow")
    await db_session.commit()

    new_offers = [_raw_offer(), _raw_offer()]
    calls: list[int] = []

    def _fake_get(url: str, *, params: dict[str, Any], **kw: Any) -> _FakeResponse:
        page_index = params["pageIndex"]
        calls.append(page_index)
        if page_index == 0:
            return _FakeResponse(json_data=_page_payload(new_offers, page_size=2))
        if page_index == 1:
            return _FakeResponse(json_data=_page_payload(already_seen_offers, page_size=2))
        raise AssertionError(f"pagination should have stopped before requesting page {page_index}")

    monkeypatch.setattr(httpx, "get", _fake_get)

    result = await run_solid_jobs_ingestion(db_session, source, campaign="recruflow")
    await db_session.commit()

    assert calls == [0, 1]
    assert result.ok is True
    assert result.fetched == 4
    assert result.created == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_solid_jobs_ingestion_force_refresh_bypasses_early_stop(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(
        db_session,
        config_json={"page_size": 2, "already_seen_stop_threshold": 2},
    )
    already_seen_offers = [_raw_offer(), _raw_offer()]
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _FakeResponse(json_data=_page_payload(already_seen_offers, page_size=2)),
    )
    await run_solid_jobs_ingestion(db_session, source, campaign="recruflow")
    await db_session.commit()

    new_offer = _raw_offer()
    calls: list[int] = []

    def _fake_get(url: str, *, params: dict[str, Any], **kw: Any) -> _FakeResponse:
        page_index = params["pageIndex"]
        calls.append(page_index)
        if page_index in (0, 1):
            return _FakeResponse(json_data=_page_payload(already_seen_offers, page_size=2))
        if page_index == 2:
            return _FakeResponse(json_data=_page_payload([new_offer], page_size=2))
        raise AssertionError(f"unexpected page request page_index={page_index}")

    monkeypatch.setattr(httpx, "get", _fake_get)

    result = await run_solid_jobs_ingestion(
        db_session, source, campaign="recruflow", force_refresh=True
    )
    await db_session.commit()

    assert calls == [0, 1, 2]
    assert result.ok is True
    assert result.fetched == 5
    assert result.created == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_solid_jobs_ingestion_respects_max_pages_ceiling(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Every page returns a brand-new, full-size page (never already-seen, never short), so only
    # max_pages caps the loop -- confirms the ceiling still applies even when the early-stop and
    # short-page end-of-results signal never fire.
    source = await _create_source(db_session, config_json={"page_size": 1, "max_pages": 3})
    calls: list[int] = []

    def _fake_get(url: str, *, params: dict[str, Any], **kw: Any) -> _FakeResponse:
        calls.append(params["pageIndex"])
        return _FakeResponse(json_data=_page_payload([_raw_offer()], page_size=1))

    monkeypatch.setattr(httpx, "get", _fake_get)

    result = await run_solid_jobs_ingestion(db_session, source, campaign="recruflow")
    await db_session.commit()

    assert calls == [0, 1, 2]
    assert result.ok is True
    assert result.fetched == 3
    assert result.created == 3
