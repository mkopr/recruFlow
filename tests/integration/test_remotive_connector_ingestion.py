from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.connectors.remotive import REMOTIVE_URL, RemotiveConnector
from app.db.models import IngestionFailure, Source
from app.db.models import Offer as OfferModel
from app.ingestion.normalize import REMOTIVE
from app.llm.matcher import _MatcherOutput
from app.scoring.batch import run_batch_scoring
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_batch_scoring import _create_profile, _delete_sources_and_dependents
from tests.integration.test_langchain_matcher_batch import _STRONG_OUTPUT_KWARGS, _FakeChain
from tests.integration.test_offers_routes import _deactivate_all_profiles


class _FakeResponse:
    def __init__(self, *, json_data: Any = None) -> None:
        self._json_data = json_data

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._json_data


async def _create_source(session: AsyncSession, connector: str | None = None) -> Source:
    source = Source(name=f"remotive-{uuid4()}", connector=connector, config_json={})
    session.add(source)
    await session.flush()
    return source


def _job(job_id: int, **overrides: Any) -> dict[str, Any]:
    job: dict[str, Any] = {
        "id": job_id,
        "url": f"https://remotive.com/remote-jobs/software-dev/backend-engineer-{job_id}",
        "title": f"Backend Engineer {job_id}",
        "company_name": "Acme",
        "category": "Software Development",
        "tags": ["python", "backend"],
        "job_type": "full_time",
        "publication_date": "2026-06-01T00:00:00",
        "candidate_required_location": "Worldwide",
        "salary": "$70,000 - $90,000",
        "description": "great role",
    }
    job.update(overrides)
    return job


def _single_response(jobs: list[dict[str, Any]]) -> Any:
    # BUG45: the connector now makes exactly one request per run (Remotive's `category`
    # query param turned out to be a no-op live), so the fake transport no longer needs to
    # route by category -- every call gets the same full jobs list back.
    def _get(url: str, params: dict[str, Any] | None = None, **kwargs: Any) -> _FakeResponse:
        assert url == REMOTIVE_URL
        assert params == {}
        return _FakeResponse(json_data={"jobs": jobs})

    return _get


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_remotive_ingestion_persists_and_maps_offers_across_categories(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    source.config_json = {"categories": ["software-development", "qa"]}
    job1 = _job(int(uuid4().int % 1_000_000), category="Software Development")
    job2 = _job(int(uuid4().int % 1_000_000), category="Quality Assurance")

    monkeypatch.setattr(httpx, "get", _single_response([job1, job2]))

    result = await RemotiveConnector().run(db_session, source)
    await db_session.commit()

    assert result.ok is True
    assert result.fetched == 2
    assert result.created == 2

    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 2
    jobs_by_url = {job1["url"]: job1, job2["url"]: job2}
    for row in rows:
        assert row.remote is True
        assert row.raw_payload == jobs_by_url[row.canonical_url]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_remotive_ingestion_respects_fetch_range_with_naive_publication_date(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression test: Remotive's `publication_date` has no timezone suffix (confirmed live
    # 2026-07-14), which crashed `run_paginated_ingestion`'s fetch-range comparison with
    # "can't compare offset-naive and offset-aware datetimes" on every real run before
    # `_normalize_posted_at` was added. A configured `since` bound must filter correctly
    # instead of raising.
    source = await _create_source(db_session)
    source.config_json = {
        "categories": ["software-development"],
        "fetch_range": {"mode": "range", "since": "2026-07-01T00:00:00+00:00", "until": None},
    }
    in_range_job = _job(int(uuid4().int % 1_000_000), publication_date="2026-07-13T07:05:10")
    out_of_range_job = _job(int(uuid4().int % 1_000_000), publication_date="2026-06-01T00:00:00")

    monkeypatch.setattr(httpx, "get", _single_response([in_range_job, out_of_range_job]))

    result = await RemotiveConnector().run(db_session, source)
    await db_session.commit()

    assert result.ok is True
    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].canonical_url == in_range_job["url"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_remotive_ingestion_rerun_dedups_across_runs(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    source.config_json = {"categories": ["software-development"]}
    job = _job(int(uuid4().int % 1_000_000))

    monkeypatch.setattr(httpx, "get", _single_response([job]))

    first = await RemotiveConnector().run(db_session, source)
    await db_session.commit()
    second = await RemotiveConnector().run(db_session, source)
    await db_session.commit()

    assert first.created == 1
    assert second.fetched == 1
    assert second.created == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_remotive_ingestion_excludes_non_configured_categories(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # BUG45: this scope used to be (unintentionally) unenforced, because Remotive's
    # `category` query param is a no-op live -- Sales/Marketing/Medical jobs had been
    # silently reaching the DB despite `categories` only listing software-development. The
    # client-side filter added in `fetch_page` is what actually makes this scope real.
    source = await _create_source(db_session)
    source.config_json = {"categories": ["software-development"]}
    software_job = _job(int(uuid4().int % 1_000_000), category="Software Development")
    sales_job = _job(
        int(uuid4().int % 1_000_000),
        category="Sales",
        url="https://remotive.com/remote-jobs/sales/sales-only",
    )

    calls: list[dict[str, Any]] = []

    def _get(url: str, params: dict[str, Any] | None = None, **kwargs: Any) -> _FakeResponse:
        assert params == {}
        calls.append(params)
        return _FakeResponse(json_data={"jobs": [software_job, sales_job]})

    monkeypatch.setattr(httpx, "get", _get)

    result = await RemotiveConnector().run(db_session, source)
    await db_session.commit()

    assert result.created == 1
    assert len(calls) == 1

    sales_row = await db_session.scalar(
        select(OfferModel).where(OfferModel.canonical_url == sales_job["url"])
    )
    assert sales_row is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_remotive_ingestion_records_dead_letter_on_malformed_job_element(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    source.config_json = {"categories": ["software-development"]}
    good_job = _job(int(uuid4().int % 1_000_000))
    bad_job = _job(int(uuid4().int % 1_000_000), company_name="", title="")

    monkeypatch.setattr(httpx, "get", _single_response([good_job, bad_job]))

    result = await RemotiveConnector().run(db_session, source)
    await db_session.commit()

    assert result.created == 1
    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].canonical_url == good_job["url"]

    failures = (
        (
            await db_session.execute(
                select(IngestionFailure).where(IngestionFailure.source_id == source.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(failures) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_remotive_ingestion_scoring_eligibility(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session, connector=REMOTIVE)
    source.config_json = {"categories": ["software-development"]}
    job = _job(int(uuid4().int % 1_000_000))
    monkeypatch.setattr(httpx, "get", _single_response([job]))

    try:
        ingestion_result = await RemotiveConnector().run(db_session, source)
        await db_session.commit()
        assert ingestion_result.created == 1

        await _deactivate_all_profiles(db_session)
        await _create_profile(db_session)
        await db_session.commit()

        summary = await run_batch_scoring(
            db_session,
            connectors={REMOTIVE},
            chain_factory=lambda: _FakeChain(_MatcherOutput(**_STRONG_OUTPUT_KWARGS)),
        )
        await db_session.commit()

        assert summary.scored == 1
        assert summary.failed == 0
    finally:
        await _delete_sources_and_dependents(db_session, [source.id])
