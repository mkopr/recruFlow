from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.connectors.solid_jobs import SolidJobsConnector
from app.db.models import IngestionFailure, Source
from app.db.models import Offer as OfferModel
from app.db.models import Profile as ProfileModel
from app.db.session import get_engine, get_sessionmaker
from app.ingestion.normalize import SOLID_JOBS
from app.ingestion.types import IngestionResult
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


async def _deactivate_all_profiles(session: AsyncSession) -> None:
    await session.execute(update(ProfileModel).values(is_active=False))
    await session.commit()


async def _create_active_profile(session: AsyncSession, *, skills: list[dict[str, Any]]) -> None:
    profile = ProfileModel(name=f"profile-{uuid4()}", is_active=True, data={"skills": skills})
    session.add(profile)
    await session.flush()


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

    result = await SolidJobsConnector(campaign="recruflow").run(db_session, source)
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

    result = await SolidJobsConnector(campaign="recruflow").run(db_session, source)
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

    result = await SolidJobsConnector(campaign="recruflow").run(db_session, source)
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

    result = await SolidJobsConnector(campaign="recruflow").run(db_session, source)
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

    result = await SolidJobsConnector(campaign="recruflow").run(db_session, source)
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

    first = await SolidJobsConnector(campaign="recruflow").run(db_session, source)
    await db_session.commit()
    second = await SolidJobsConnector(campaign="recruflow").run(db_session, source)
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

    await SolidJobsConnector(campaign="recruflow").run(db_session, source)
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

    await SolidJobsConnector(campaign="recruflow").run(db_session, source)
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
    await SolidJobsConnector(campaign="recruflow").run(db_session, source)
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

    result = await SolidJobsConnector(campaign="recruflow").run(db_session, source)
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
    await SolidJobsConnector(campaign="recruflow").run(db_session, source)
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

    result = await SolidJobsConnector(campaign="recruflow").run(
        db_session, source, force_refresh=True
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

    result = await SolidJobsConnector(campaign="recruflow").run(db_session, source)
    await db_session.commit()

    assert calls == [0, 1, 2]
    assert result.ok is True
    assert result.fetched == 3
    assert result.created == 3


# US34 -- fetch_range integration for this connector. justjoinit/nofluffjobs get at least one
# equivalent smoke test added by the same pattern; the filtering logic itself lives in the
# shared runner (see tests/test_ingestion_runner.py) but each connector's raw posted_at shape
# (an ISO string here, an already-parsed datetime for nofluffjobs) is worth a direct check.


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_solid_jobs_ingestion_range_mode_skips_offers_outside_since_until(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    in_range = _raw_offer(validFrom="2026-06-15T00:00:00Z")
    out_of_range = _raw_offer(validFrom="2026-05-01T00:00:00Z")
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _FakeResponse(json_data=_page_payload([in_range, out_of_range])),
    )

    result = await SolidJobsConnector(campaign="recruflow").run(db_session, source)
    await db_session.commit()

    assert result.fetched == 2
    assert result.created == 1
    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].raw_payload["jobOfferKey"] == in_range["jobOfferKey"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_solid_jobs_ingestion_all_mode_bypasses_date_filtering(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session, config_json={"fetch_range": {"mode": "all"}})
    offer_a = _raw_offer(validFrom="2026-06-15T00:00:00Z")
    offer_b = _raw_offer(validFrom="2026-05-01T00:00:00Z")
    monkeypatch.setattr(
        httpx, "get", lambda *a, **kw: _FakeResponse(json_data=_page_payload([offer_a, offer_b]))
    )

    result = await SolidJobsConnector(campaign="recruflow").run(db_session, source)
    await db_session.commit()

    assert result.fetched == 2
    assert result.created == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_solid_jobs_ingestion_range_filter_does_not_trip_already_seen_early_stop(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(
        db_session,
        config_json={
            "page_size": 2,
            "already_seen_stop_threshold": 2,
            "fetch_range": {
                "mode": "range",
                "since": "2026-06-01T00:00:00Z",
                "until": "2026-06-30T00:00:00Z",
            },
        },
    )
    # Page 1's offers are newer than `until` (filtered out, not "old"), so they must never
    # trip the already-seen threshold and prevent page 2 -- which holds the one in-range offer
    # -- from being fetched.
    out_of_range_offers = [
        _raw_offer(validFrom="2026-07-15T00:00:00Z"),
        _raw_offer(validFrom="2026-07-16T00:00:00Z"),
    ]
    in_range_offer = _raw_offer(validFrom="2026-06-15T00:00:00Z")
    calls: list[int] = []

    def _fake_get(url: str, *, params: dict[str, Any], **kw: Any) -> _FakeResponse:
        page_index = params["pageIndex"]
        calls.append(page_index)
        if page_index == 0:
            return _FakeResponse(json_data=_page_payload(out_of_range_offers, page_size=2))
        if page_index == 1:
            return _FakeResponse(json_data=_page_payload([in_range_offer], page_size=2))
        raise AssertionError(f"pagination should have stopped before requesting page {page_index}")

    monkeypatch.setattr(httpx, "get", _fake_get)

    result = await SolidJobsConnector(campaign="recruflow").run(db_session, source)
    await db_session.commit()

    assert calls == [0, 1]
    assert result.fetched == 3
    assert result.created == 1


# US47 -- Fetch Scope filtered-mode integration for SOLID.Jobs.


@pytest.mark.integration
@pytest.mark.asyncio
async def test_filtered_fetch_scope_issues_one_request_per_hard_skill_and_dedups_offers(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _deactivate_all_profiles(db_session)
    await _create_active_profile(
        db_session, skills=[{"name": "Python", "hard": True}, {"name": "Go", "hard": True}]
    )
    await db_session.commit()

    shared_offer = _raw_offer()
    python_only_offer = _raw_offer()
    go_only_offer = _raw_offer()
    source = await _create_source(db_session, config_json={"fetch_scope": {"mode": "filtered"}})

    requested_terms: list[str] = []

    def _fake_get(url: str, *, params: dict[str, Any], **kw: Any) -> _FakeResponse:
        term = params["search.searchTerm"]
        requested_terms.append(term)
        if term == "Python":
            return _FakeResponse(json_data=_page_payload([python_only_offer, shared_offer]))
        if term == "Go":
            return _FakeResponse(json_data=_page_payload([go_only_offer, shared_offer]))
        raise AssertionError(f"unexpected search term: {term!r}")

    monkeypatch.setattr(httpx, "get", _fake_get)

    result = await SolidJobsConnector(campaign="recruflow").run(db_session, source)
    await db_session.commit()

    assert sorted(requested_terms) == ["Go", "Python"]
    assert result.ok is True
    assert result.fetched == 4
    assert result.created == 3
    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 3


@pytest.mark.integration
@pytest.mark.asyncio
async def test_filtered_fetch_scope_blocked_when_active_profile_has_no_hard_skills(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _deactivate_all_profiles(db_session)
    await _create_active_profile(db_session, skills=[{"name": "Python", "hard": False}])
    await db_session.commit()

    source = await _create_source(db_session, config_json={"fetch_scope": {"mode": "filtered"}})

    def _fail(*a: Any, **kw: Any) -> None:
        raise AssertionError("must not fetch when fetch scope is blocked")

    monkeypatch.setattr(httpx, "get", _fail)

    result = await SolidJobsConnector(campaign="recruflow").run(db_session, source)
    await db_session.commit()

    assert result.ok is False
    assert result.error_message is not None
    assert "no starred" in result.error_message or "hard skills" in result.error_message


@pytest.mark.integration
@pytest.mark.asyncio
async def test_filtered_fetch_scope_blocked_when_no_active_profile(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _deactivate_all_profiles(db_session)

    source = await _create_source(db_session, config_json={"fetch_scope": {"mode": "filtered"}})

    def _fail(*a: Any, **kw: Any) -> None:
        raise AssertionError("must not fetch when fetch scope is blocked")

    monkeypatch.setattr(httpx, "get", _fail)

    result = await SolidJobsConnector(campaign="recruflow").run(db_session, source)
    await db_session.commit()

    assert result.ok is False
    assert result.error_message is not None
    assert "no active profile" in result.error_message


@pytest.mark.integration
@pytest.mark.asyncio
async def test_filtered_fetch_scope_blocked_run_is_recorded_and_retryable_via_dlq(
    scheduled_client: httpx.AsyncClient,
) -> None:
    # End-to-end through the real HTTP surface: PUT fetch-scope filtered -> POST /ingest ->
    # GET /failures/ingestion -> POST retry, reusing BUG37's existing "IngestionResult(ok=False)
    # becomes a RUN_FETCH_FAILED row" pathway with zero new DLQ code (US47).
    engine = get_engine()
    sessionmaker = get_sessionmaker(engine)
    try:
        async with sessionmaker() as session:
            await session.execute(update(ProfileModel).values(is_active=False))
            await session.commit()

        put_response = await scheduled_client.put(
            "/scheduler/sources/solid_jobs/fetch-scope", json={"mode": "filtered"}
        )
        assert put_response.status_code == 200

        ingest_response = await scheduled_client.post("/ingest/solid_jobs")
        assert ingest_response.status_code == 200
        assert ingest_response.json()["ok"] is False

        async with sessionmaker() as session:
            source = await session.scalar(select(Source).where(Source.connector == SOLID_JOBS))
            assert source is not None
            failure = await session.scalar(
                select(IngestionFailure).where(IngestionFailure.source_id == source.id)
            )
            assert failure is not None
            assert failure.failure_type == "run_fetch_failed"
            failure_id = failure.id

        failures_response = await scheduled_client.get(
            "/failures/ingestion", params={"source": SOLID_JOBS}
        )
        assert failures_response.status_code == 200
        listed_ids = {item["id"] for item in failures_response.json()["items"]}
        assert failure_id in listed_ids

        retry_response = await scheduled_client.post(f"/failures/ingestion/{failure_id}/retry")
        assert retry_response.status_code == 200
    finally:
        # Reset the real, singleton solid_jobs Source row back to defaults so later tests in
        # this suite that hit /ingest/solid_jobs or /scheduler/... aren't silently blocked by
        # this test's fetch-scope change (mirrors BUG28's "tests must not leak shared state").
        reset_response = await scheduled_client.put(
            "/scheduler/sources/solid_jobs/fetch-scope", json={"mode": "all"}
        )
        assert reset_response.status_code == 200
