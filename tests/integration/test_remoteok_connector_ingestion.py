from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.connectors.remoteok import REMOTEOK_URL, RemoteOKConnector
from app.db.models import IngestionFailure, Source
from app.db.models import Offer as OfferModel
from app.ingestion.normalize import REMOTEOK
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
    source = Source(name=f"remoteok-{uuid4()}", connector=connector, config_json={})
    session.add(source)
    await session.flush()
    return source


def _job(job_id: int, **overrides: Any) -> dict[str, Any]:
    job: dict[str, Any] = {
        "id": job_id,
        "slug": f"acme-backend-engineer-{job_id}",
        "epoch": 1782888932,
        "date": "2026-06-01T00:00:00Z",
        "company": "Acme",
        "position": f"Backend Engineer {job_id}",
        "tags": ["python", "backend"],
        "description": "great role",
        "location": "Worldwide",
        "apply_url": f"https://remoteok.com/apply/{job_id}",
        "url": f"https://remoteok.com/remote-jobs/{job_id}",
        "salary_min": 60000,
        "salary_max": 90000,
    }
    job.update(overrides)
    return job


def _payload(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"last_updated": "x", "legal": "y"}, *jobs]


def _router(payload: list[dict[str, Any]]) -> Any:
    def _get(url: str, **kwargs: Any) -> _FakeResponse:
        assert url == REMOTEOK_URL
        return _FakeResponse(json_data=payload)

    return _get


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_remoteok_ingestion_persists_and_maps_offers(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    job1, job2 = _job(int(uuid4().int % 1_000_000)), _job(int(uuid4().int % 1_000_000))

    monkeypatch.setattr(httpx, "get", _router(_payload([job1, job2])))

    result = await RemoteOKConnector().run(db_session, source)
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
        assert row.seniority is None
        assert row.raw_payload == jobs_by_url[row.canonical_url]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_remoteok_ingestion_dedups_on_rerun(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    job1, job2 = _job(int(uuid4().int % 1_000_000)), _job(int(uuid4().int % 1_000_000))
    payload = _payload([job1, job2])

    monkeypatch.setattr(httpx, "get", _router(payload))

    first = await RemoteOKConnector().run(db_session, source)
    await db_session.commit()
    second = await RemoteOKConnector().run(db_session, source)
    await db_session.commit()

    assert first.fetched == 2
    assert first.created == 2
    assert second.fetched == 2
    assert second.created == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_remoteok_ingestion_records_dead_letter_on_malformed_job_element(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    good_job = _job(int(uuid4().int % 1_000_000))
    bad_job = _job(int(uuid4().int % 1_000_000), company="", position="")

    monkeypatch.setattr(httpx, "get", _router(_payload([good_job, bad_job])))

    result = await RemoteOKConnector().run(db_session, source)
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
async def test_run_remoteok_ingestion_scoring_eligibility(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session, connector=REMOTEOK)
    job = _job(int(uuid4().int % 1_000_000))
    monkeypatch.setattr(httpx, "get", _router(_payload([job])))

    try:
        ingestion_result = await RemoteOKConnector().run(db_session, source)
        await db_session.commit()
        assert ingestion_result.created == 1

        await _deactivate_all_profiles(db_session)
        await _create_profile(db_session)
        await db_session.commit()

        summary = await run_batch_scoring(
            db_session,
            connectors={REMOTEOK},
            chain_factory=lambda: _FakeChain(_MatcherOutput(**_STRONG_OUTPUT_KWARGS)),
        )
        await db_session.commit()

        assert summary.scored == 1
        assert summary.failed == 0
    finally:
        await _delete_sources_and_dependents(db_session, [source.id])
