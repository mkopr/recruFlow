from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.connectors.justjoinit import JustJoinItConnector
from app.connectors.nofluffjobs import NoFluffJobsConnector
from app.connectors.solid_jobs import SolidJobsConnector
from app.db.models import Offer as OfferModel
from app.db.models import Source
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class _FakeResponse:
    def __init__(self, *, json_data: Any = None) -> None:
        self._json_data = json_data

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._json_data


async def _create_source(session: AsyncSession, name_prefix: str) -> Source:
    source = Source(name=f"{name_prefix}-{uuid4()}", config_json={})
    session.add(source)
    await session.flush()
    return source


def _solid_jobs_raw(**overrides: Any) -> dict[str, Any]:
    offer: dict[str, Any] = {
        "jobOfferKey": str(uuid4()),
        "url": f"https://solid.jobs/o/{uuid4()}",
        "title": "Backend Engineer",
        "company": "Acme",
        "locations": ["Warszawa"],
        "isRemote": True,
        "experienceLevel": "Senior",
        "salary": {"from": 18000, "to": 24000, "currency": "PLN", "employmentType": "b2b"},
        "validFrom": "2026-06-01T00:00:00Z",
    }
    offer.update(overrides)
    return offer


def _justjoinit_raw(**overrides: Any) -> dict[str, Any]:
    offer: dict[str, Any] = {
        "guid": str(uuid4()),
        "slug": f"acme-backend-engineer-{uuid4()}",
        "title": "Backend Engineer",
        "workplaceType": "remote",
        "experienceLevel": "senior",
        "companyName": "Acme",
        "locations": [{"city": "Warszawa"}],
        "employmentTypes": [{"from": 18000.0, "to": 24000.0, "currency": "PLN", "type": "b2b"}],
        "publishedAt": "2026-06-01T00:00:00Z",
    }
    offer.update(overrides)
    return offer


def _nofluffjobs_raw(**overrides: Any) -> dict[str, Any]:
    offer: dict[str, Any] = {
        "id": f"backend-engineer-acme-{uuid4()}",
        "url": f"backend-engineer-acme-{uuid4()}",
        "reference": str(uuid4()),
        "title": "Backend Engineer",
        "name": "Acme",
        "location": {"places": [{"city": "Warszawa"}], "fullyRemote": True},
        "seniority": ["Senior"],
        "salary": {"from": 18000.0, "to": 24000.0, "currency": "PLN", "type": "b2b"},
        "posted": 1782888932251,
    }
    offer.update(overrides)
    return offer


def _solid_jobs_payload(offers: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "jobs": offers,
        "pageIndex": 0,
        "pageSize": 100,
        "totalCount": len(offers),
        "totalPages": 1,
    }


def _justjoinit_payload(offers: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "data": offers,
        "meta": {"next": {"cursor": None, "itemsCount": len(offers)}},
    }


def _nofluffjobs_payload(offers: list[dict[str, Any]]) -> dict[str, Any]:
    return {"postings": offers, "totalCount": len(offers), "totalPages": 1}


async def _rows_for_source(session: AsyncSession, source_id: int) -> list[OfferModel]:
    result = await session.execute(select(OfferModel).where(OfferModel.source_id == source_id))
    return list(result.scalars().all())


# US46 finding #7: this file intentionally covers only the original 3 cursor-paginated JSON
# connectors (SOLID.Jobs, JustJoin.it, NoFluffJobs) because they share one mocking shape
# (monkeypatch.setattr(httpx, "get", ...)). The 6 newer connectors' cross-cutting
# normalization behavior (remote-flag, seniority, salary-currency) is already exercised
# per-connector in each connector's own tests/test_<name>_connector.py map_offer tests --
# Bulldogjob/Rocket Jobs need sitemap+detail-page double-fetch mocking and Pracuj needs
# Playwright mocking this file has no precedent for, so extending this file to all 9 would add
# new test infrastructure rather than reuse the existing shape. Naming this scope explicitly
# so a future reader doesn't mistake it for an oversight.


@pytest.mark.integration
@pytest.mark.asyncio
async def test_all_three_connectors_run_end_to_end_and_persist_valid_offers(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    solid_source = await _create_source(db_session, "solid-jobs")
    justjoinit_source = await _create_source(db_session, "justjoinit")
    nofluffjobs_source = await _create_source(db_session, "nofluffjobs")

    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _FakeResponse(json_data=_solid_jobs_payload([_solid_jobs_raw()])),
    )
    solid_result = await SolidJobsConnector(campaign="recruflow").run(db_session, solid_source)
    await db_session.commit()

    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _FakeResponse(json_data=_justjoinit_payload([_justjoinit_raw()])),
    )
    justjoinit_result = await JustJoinItConnector().run(db_session, justjoinit_source)
    await db_session.commit()

    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _FakeResponse(json_data=_nofluffjobs_payload([_nofluffjobs_raw()])),
    )
    nofluffjobs_result = await NoFluffJobsConnector().run(db_session, nofluffjobs_source)
    await db_session.commit()

    assert solid_result.ok is True
    assert justjoinit_result.ok is True
    assert nofluffjobs_result.ok is True

    assert len(await _rows_for_source(db_session, solid_source.id)) == 1
    assert len(await _rows_for_source(db_session, justjoinit_source.id)) == 1
    assert len(await _rows_for_source(db_session, nofluffjobs_source.id)) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_salary_normalised_to_pln_monthly_across_all_sources(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    solid_source = await _create_source(db_session, "solid-jobs")
    justjoinit_source = await _create_source(db_session, "justjoinit")
    nofluffjobs_source = await _create_source(db_session, "nofluffjobs")

    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _FakeResponse(json_data=_solid_jobs_payload([_solid_jobs_raw()])),
    )
    await SolidJobsConnector(campaign="recruflow").run(db_session, solid_source)
    await db_session.commit()

    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _FakeResponse(json_data=_justjoinit_payload([_justjoinit_raw()])),
    )
    await JustJoinItConnector().run(db_session, justjoinit_source)
    await db_session.commit()

    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _FakeResponse(json_data=_nofluffjobs_payload([_nofluffjobs_raw()])),
    )
    await NoFluffJobsConnector().run(db_session, nofluffjobs_source)
    await db_session.commit()

    solid_rows = await _rows_for_source(db_session, solid_source.id)
    justjoinit_rows = await _rows_for_source(db_session, justjoinit_source.id)
    nofluffjobs_rows = await _rows_for_source(db_session, nofluffjobs_source.id)

    assert solid_rows[0].salary_currency == "PLN"
    assert justjoinit_rows[0].salary_currency == "PLN"
    assert nofluffjobs_rows[0].salary_currency == "PLN"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_remote_flag_canonical_across_all_sources(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    solid_source = await _create_source(db_session, "solid-jobs")
    justjoinit_source = await _create_source(db_session, "justjoinit")
    nofluffjobs_source = await _create_source(db_session, "nofluffjobs")

    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _FakeResponse(
            json_data=_solid_jobs_payload([_solid_jobs_raw(isRemote=True)])
        ),
    )
    await SolidJobsConnector(campaign="recruflow").run(db_session, solid_source)
    await db_session.commit()

    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _FakeResponse(
            json_data=_justjoinit_payload([_justjoinit_raw(workplaceType="remote")])
        ),
    )
    await JustJoinItConnector().run(db_session, justjoinit_source)
    await db_session.commit()

    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _FakeResponse(
            json_data=_nofluffjobs_payload(
                [_nofluffjobs_raw(location={"places": [{"city": "Warszawa"}], "fullyRemote": True})]
            )
        ),
    )
    await NoFluffJobsConnector().run(db_session, nofluffjobs_source)
    await db_session.commit()

    assert (await _rows_for_source(db_session, solid_source.id))[0].remote is True
    assert (await _rows_for_source(db_session, justjoinit_source.id))[0].remote is True
    assert (await _rows_for_source(db_session, nofluffjobs_source.id))[0].remote is True

    solid_source2 = await _create_source(db_session, "solid-jobs")
    justjoinit_source2 = await _create_source(db_session, "justjoinit")
    nofluffjobs_source2 = await _create_source(db_session, "nofluffjobs")

    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _FakeResponse(
            json_data=_solid_jobs_payload([_solid_jobs_raw(isRemote=False)])
        ),
    )
    await SolidJobsConnector(campaign="recruflow").run(db_session, solid_source2)
    await db_session.commit()

    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _FakeResponse(
            json_data=_justjoinit_payload([_justjoinit_raw(workplaceType="office")])
        ),
    )
    await JustJoinItConnector().run(db_session, justjoinit_source2)
    await db_session.commit()

    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _FakeResponse(
            json_data=_nofluffjobs_payload(
                [
                    _nofluffjobs_raw(
                        location={"places": [{"city": "Warszawa"}], "fullyRemote": False}
                    )
                ]
            )
        ),
    )
    await NoFluffJobsConnector().run(db_session, nofluffjobs_source2)
    await db_session.commit()

    assert (await _rows_for_source(db_session, solid_source2.id))[0].remote is False
    assert (await _rows_for_source(db_session, justjoinit_source2.id))[0].remote is False
    assert (await _rows_for_source(db_session, nofluffjobs_source2.id))[0].remote is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_seniority_canonical_across_all_sources(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    solid_source = await _create_source(db_session, "solid-jobs")
    justjoinit_source = await _create_source(db_session, "justjoinit")
    nofluffjobs_source = await _create_source(db_session, "nofluffjobs")

    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _FakeResponse(
            json_data=_solid_jobs_payload([_solid_jobs_raw(experienceLevel="Senior")])
        ),
    )
    await SolidJobsConnector(campaign="recruflow").run(db_session, solid_source)
    await db_session.commit()

    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _FakeResponse(
            json_data=_justjoinit_payload([_justjoinit_raw(experienceLevel="senior")])
        ),
    )
    await JustJoinItConnector().run(db_session, justjoinit_source)
    await db_session.commit()

    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _FakeResponse(
            json_data=_nofluffjobs_payload([_nofluffjobs_raw(seniority=["Senior"])])
        ),
    )
    await NoFluffJobsConnector().run(db_session, nofluffjobs_source)
    await db_session.commit()

    assert (await _rows_for_source(db_session, solid_source.id))[0].seniority == "senior"
    assert (await _rows_for_source(db_session, justjoinit_source.id))[0].seniority == "senior"
    assert (await _rows_for_source(db_session, nofluffjobs_source.id))[0].seniority == "senior"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cross_posted_offer_is_stored_as_separate_rows_per_source(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    justjoinit_source = await _create_source(db_session, "justjoinit")
    nofluffjobs_source = await _create_source(db_session, "nofluffjobs")

    shared_title = "Staff Backend Engineer"
    shared_company = "Acme"
    shared_city = "Warszawa"

    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _FakeResponse(
            json_data=_justjoinit_payload(
                [
                    _justjoinit_raw(
                        title=shared_title,
                        companyName=shared_company,
                        locations=[{"city": shared_city}],
                    )
                ]
            )
        ),
    )
    await JustJoinItConnector().run(db_session, justjoinit_source)
    await db_session.commit()

    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _FakeResponse(
            json_data=_nofluffjobs_payload(
                [
                    _nofluffjobs_raw(
                        title=shared_title,
                        name=shared_company,
                        location={"places": [{"city": shared_city}], "fullyRemote": False},
                    )
                ]
            )
        ),
    )
    await NoFluffJobsConnector().run(db_session, nofluffjobs_source)
    await db_session.commit()

    justjoinit_rows = await _rows_for_source(db_session, justjoinit_source.id)
    nofluffjobs_rows = await _rows_for_source(db_session, nofluffjobs_source.id)

    assert len(justjoinit_rows) == 1
    assert len(nofluffjobs_rows) == 1
    assert justjoinit_rows[0].source_id != nofluffjobs_rows[0].source_id
    assert justjoinit_rows[0].dedup_hash != nofluffjobs_rows[0].dedup_hash

    all_offer_ids = {row.id for row in justjoinit_rows} | {row.id for row in nofluffjobs_rows}
    assert len(all_offer_ids) == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_missing_optional_field_stored_as_null_not_placeholder(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    justjoinit_source = await _create_source(db_session, "justjoinit")

    raw = {
        "guid": str(uuid4()),
        "slug": f"acme-backend-engineer-{uuid4()}",
        "title": "Backend Engineer",
        "companyName": "Acme",
    }
    monkeypatch.setattr(
        httpx, "get", lambda *a, **kw: _FakeResponse(json_data=_justjoinit_payload([raw]))
    )

    await JustJoinItConnector().run(db_session, justjoinit_source)
    await db_session.commit()

    rows = await _rows_for_source(db_session, justjoinit_source.id)
    assert len(rows) == 1
    row = rows[0]
    assert row.location is None
    assert row.seniority is None
    assert row.salary_min is None
    assert row.salary_max is None
    assert row.contract_type is None
    assert row.remote is False
