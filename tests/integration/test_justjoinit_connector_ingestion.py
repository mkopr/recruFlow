from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.connectors.justjoinit import run_justjoinit_ingestion
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
    source = Source(name=f"justjoinit-{uuid4()}", config_json=config_json or {})
    session.add(source)
    await session.flush()
    return source


def _raw_offer(**overrides: Any) -> dict[str, Any]:
    offer: dict[str, Any] = {
        "guid": str(uuid4()),
        "slug": f"acme-backend-engineer-{uuid4()}",
        "title": "Backend Engineer",
        "workplaceType": "remote",
        "workingTime": "full_time",
        "experienceLevel": "senior",
        "city": "Warszawa",
        "companyName": "Acme",
        "locations": [{"city": "Warszawa"}],
        "employmentTypes": [{"from": 18000.0, "to": 24000.0, "currency": "PLN", "type": "b2b"}],
        "publishedAt": "2026-06-01T00:00:00Z",
    }
    offer.update(overrides)
    return offer


def _offers_payload(offers: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "data": offers,
        "meta": {
            "from": 0,
            "totalItems": len(offers),
            "prev": {"cursor": None, "itemsCount": len(offers)},
            "next": {"cursor": None, "itemsCount": len(offers)},
        },
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_justjoinit_ingestion_persists_and_maps_offers(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    offer = _raw_offer()
    monkeypatch.setattr(
        httpx, "get", lambda *a, **kw: _FakeResponse(json_data=_offers_payload([offer]))
    )

    result = await run_justjoinit_ingestion(db_session, source)
    await db_session.commit()

    assert result == IngestionResult(ok=True, fetched=1, created=1)
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
async def test_run_justjoinit_ingestion_handles_zero_offers(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(json_data=_offers_payload([])))

    result = await run_justjoinit_ingestion(db_session, source)
    await db_session.commit()

    assert result == IngestionResult(ok=True, fetched=0, created=0)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_justjoinit_ingestion_returns_not_ok_on_transport_failure(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)

    def _raise(*a: Any, **kw: Any) -> None:
        raise httpx.ConnectError("connection failed")

    monkeypatch.setattr(httpx, "get", _raise)

    result = await run_justjoinit_ingestion(db_session, source)
    await db_session.commit()

    assert result == IngestionResult(
        ok=False, fetched=0, created=0, error_message="failed to fetch JustJoin.it offers"
    )
    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_justjoinit_ingestion_returns_not_ok_on_unexpected_shape(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    monkeypatch.setattr(
        httpx, "get", lambda *a, **kw: _FakeResponse(json_data={"unexpected": "shape"})
    )

    result = await run_justjoinit_ingestion(db_session, source)
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
async def test_run_justjoinit_ingestion_skips_invalid_offer_without_crashing(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    valid_offer = _raw_offer()
    invalid_offer = _raw_offer(title="")
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _FakeResponse(json_data=_offers_payload([valid_offer, invalid_offer])),
    )

    result = await run_justjoinit_ingestion(db_session, source)
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
async def test_run_justjoinit_ingestion_dedups_on_reingest(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    offer = _raw_offer()
    monkeypatch.setattr(
        httpx, "get", lambda *a, **kw: _FakeResponse(json_data=_offers_payload([offer]))
    )

    first = await run_justjoinit_ingestion(db_session, source)
    await db_session.commit()
    second = await run_justjoinit_ingestion(db_session, source)
    await db_session.commit()

    assert first.created == 1
    assert second.created == 0
    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1


def _paged_payload(offers: list[dict[str, Any]], *, next_cursor: int | None) -> dict[str, Any]:
    return {
        "data": offers,
        "meta": {
            "from": 0,
            "totalItems": 10000,
            "prev": {"cursor": None, "itemsCount": len(offers)},
            "next": {"cursor": next_cursor, "itemsCount": len(offers)},
        },
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_justjoinit_ingestion_stops_pagination_after_consecutive_already_seen(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Pre-seed two offers that page 2 (from=2) will re-report, so the second page is
    # entirely already-seen. With already_seen_stop_threshold=2 this must stop the
    # pagination loop before a third page (from=4) is ever requested.
    source = await _create_source(
        db_session,
        config_json={
            "page_size": 2,
            "already_seen_stop_threshold": 2,
            "rate_limit_delay_seconds": 0,
        },
    )
    already_seen_offers = [_raw_offer(), _raw_offer()]
    # seed these two offers via a first run against a fake single-page response
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _FakeResponse(
            json_data=_paged_payload(already_seen_offers, next_cursor=None)
        ),
    )
    await run_justjoinit_ingestion(db_session, source)
    await db_session.commit()

    new_offers = [_raw_offer(), _raw_offer()]
    calls: list[int] = []

    def _fake_get(url: str, *, params: dict[str, Any], **kw: Any) -> _FakeResponse:
        cursor = params["from"]
        calls.append(cursor)
        if cursor == 0:
            return _FakeResponse(json_data=_paged_payload(new_offers, next_cursor=2))
        if cursor == 2:
            return _FakeResponse(json_data=_paged_payload(already_seen_offers, next_cursor=4))
        raise AssertionError(f"pagination should have stopped before requesting from={cursor}")

    monkeypatch.setattr(httpx, "get", _fake_get)

    result = await run_justjoinit_ingestion(db_session, source)
    await db_session.commit()

    assert calls == [0, 2]
    assert result.ok is True
    assert result.fetched == 4
    assert result.created == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_justjoinit_ingestion_respects_max_pages_ceiling(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Every page returns brand-new offers (never already-seen), so only max_pages caps
    # the loop -- confirms the ceiling still applies even when the early-stop never fires.
    source = await _create_source(
        db_session,
        config_json={"page_size": 1, "max_pages": 3, "rate_limit_delay_seconds": 0},
    )
    calls: list[int] = []

    def _fake_get(url: str, *, params: dict[str, Any], **kw: Any) -> _FakeResponse:
        cursor = params["from"]
        calls.append(cursor)
        return _FakeResponse(json_data=_paged_payload([_raw_offer()], next_cursor=cursor + 1))

    monkeypatch.setattr(httpx, "get", _fake_get)

    result = await run_justjoinit_ingestion(db_session, source)
    await db_session.commit()

    assert calls == [0, 1, 2]
    assert result.ok is True
    assert result.fetched == 3
    assert result.created == 3
