from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.connectors.nofluffjobs import IngestionResult, run_nofluffjobs_ingestion
from app.db.models import Offer as OfferModel
from app.db.models import Source
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
    source = Source(name=f"nofluffjobs-{uuid4()}", config_json=config_json or {})
    session.add(source)
    await session.flush()
    return source


def _raw_offer(**overrides: Any) -> dict[str, Any]:
    offer: dict[str, Any] = {
        "id": f"backend-engineer-acme-{uuid4()}",
        "url": f"backend-engineer-acme-{uuid4()}",
        "reference": str(uuid4()),
        "title": "Backend Engineer",
        "name": "Acme",
        "location": {
            "places": [{"city": "Warszawa"}],
            "fullyRemote": True,
        },
        "seniority": ["Senior"],
        "salary": {"from": 18000.0, "to": 24000.0, "currency": "PLN", "type": "b2b"},
        "posted": 1782888932251,
    }
    offer.update(overrides)
    return offer


def _offers_payload(offers: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "postings": offers,
        "totalCount": len(offers),
        "totalPages": 1,
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_nofluffjobs_ingestion_persists_and_maps_offers(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    offer = _raw_offer()
    monkeypatch.setattr(
        httpx, "get", lambda *a, **kw: _FakeResponse(json_data=_offers_payload([offer]))
    )

    result = await run_nofluffjobs_ingestion(db_session, source)
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
async def test_run_nofluffjobs_ingestion_handles_zero_offers(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(json_data=_offers_payload([])))

    result = await run_nofluffjobs_ingestion(db_session, source)
    await db_session.commit()

    assert result == IngestionResult(ok=True, fetched=0, created=0)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_nofluffjobs_ingestion_returns_not_ok_on_transport_failure(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)

    def _raise(*a: Any, **kw: Any) -> None:
        raise httpx.ConnectError("connection failed")

    monkeypatch.setattr(httpx, "get", _raise)

    result = await run_nofluffjobs_ingestion(db_session, source)
    await db_session.commit()

    assert result == IngestionResult(ok=False, fetched=0, created=0)
    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_nofluffjobs_ingestion_returns_not_ok_on_unexpected_shape(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    monkeypatch.setattr(
        httpx, "get", lambda *a, **kw: _FakeResponse(json_data={"unexpected": "shape"})
    )

    result = await run_nofluffjobs_ingestion(db_session, source)
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
async def test_run_nofluffjobs_ingestion_skips_invalid_offer_without_crashing(
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

    result = await run_nofluffjobs_ingestion(db_session, source)
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
async def test_run_nofluffjobs_ingestion_dedups_on_reingest(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    offer = _raw_offer()
    monkeypatch.setattr(
        httpx, "get", lambda *a, **kw: _FakeResponse(json_data=_offers_payload([offer]))
    )

    first = await run_nofluffjobs_ingestion(db_session, source)
    await db_session.commit()
    second = await run_nofluffjobs_ingestion(db_session, source)
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
async def test_run_nofluffjobs_ingestion_uses_page_size_from_config(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session, config_json={"page_size": 250})
    captured_params: dict[str, Any] = {}

    def _fake_get(*a: Any, **kw: Any) -> _FakeResponse:
        captured_params.update(kw.get("params") or {})
        return _FakeResponse(json_data=_offers_payload([]))

    monkeypatch.setattr(httpx, "get", _fake_get)

    await run_nofluffjobs_ingestion(db_session, source)
    await db_session.commit()

    assert captured_params["pageSize"] == 250
