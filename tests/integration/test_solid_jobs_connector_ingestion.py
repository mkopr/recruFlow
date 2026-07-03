import json
import subprocess
from typing import Any
from uuid import uuid4

import pytest
from app.connectors.solid_jobs import IngestionResult, run_solid_jobs_ingestion
from app.db.models import Offer as OfferModel
from app.db.models import Source
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class _FakeCompletedProcess:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


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


def _sync_stdout(offers: list[dict[str, Any]], watch: str = "my-watch") -> str:
    new = [{"watch": watch, "offer": offer} for offer in offers] or None
    return json.dumps({"watchesRun": 1, "totalSeen": len(offers), "new": new})


def _search_stdout(offers: list[dict[str, Any]]) -> str:
    return json.dumps(
        {"jobs": offers, "pageIndex": 0, "pageSize": 30, "totalCount": len(offers), "totalPages": 1}
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_solid_jobs_ingestion_persists_and_maps_offers(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    offer = _raw_offer()
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: _FakeCompletedProcess(returncode=0, stdout=_sync_stdout([offer])),
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
async def test_run_solid_jobs_ingestion_handles_no_new_offers_from_sync(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: _FakeCompletedProcess(returncode=0, stdout=_sync_stdout([])),
    )

    result = await run_solid_jobs_ingestion(db_session, source, campaign="recruflow")
    await db_session.commit()

    assert result == IngestionResult(ok=True, fetched=0, created=0)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_solid_jobs_ingestion_default_call_uses_sync_not_search(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    captured: list[list[str]] = []

    def _fake_run(argv: list[str], **kw: Any) -> _FakeCompletedProcess:
        captured.append(argv)
        return _FakeCompletedProcess(returncode=0, stdout=_sync_stdout([]))

    monkeypatch.setattr(subprocess, "run", _fake_run)

    await run_solid_jobs_ingestion(db_session, source, campaign="recruflow")

    assert captured[0][0] == "sjctl"
    assert captured[0][1] == "sync"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_solid_jobs_ingestion_force_refresh_uses_search_with_source_config(
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
    captured: list[list[str]] = []

    def _fake_run(argv: list[str], **kw: Any) -> _FakeCompletedProcess:
        captured.append(argv)
        return _FakeCompletedProcess(returncode=0, stdout=_search_stdout([]))

    monkeypatch.setattr(subprocess, "run", _fake_run)

    await run_solid_jobs_ingestion(db_session, source, campaign="recruflow", force_refresh=True)

    argv = captured[0]
    assert "search" in argv
    assert "-d" in argv and argv[argv.index("-d") + 1] == "IT"
    assert "--city" in argv and argv[argv.index("--city") + 1] == "Warsaw"
    assert "--min-salary" in argv and argv[argv.index("--min-salary") + 1] == "15000"
    assert "--experience" in argv and argv[argv.index("--experience") + 1] == "Senior"
    assert "--term" in argv and argv[argv.index("--term") + 1] == "python"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_solid_jobs_ingestion_sets_campaign_on_every_invocation(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    captured: list[list[str]] = []

    def _fake_run(argv: list[str], **kw: Any) -> _FakeCompletedProcess:
        captured.append(argv)
        return _FakeCompletedProcess(
            returncode=0,
            stdout=_sync_stdout([]) if "sync" in argv else _search_stdout([]),
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)

    await run_solid_jobs_ingestion(db_session, source, campaign="recruflow", force_refresh=False)
    await run_solid_jobs_ingestion(db_session, source, campaign="recruflow", force_refresh=True)

    for argv in captured:
        assert "--campaign" in argv
        assert argv[argv.index("--campaign") + 1] == "recruflow"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_solid_jobs_ingestion_returns_not_ok_when_sjctl_binary_missing(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)

    def _raise(*a: Any, **kw: Any) -> None:
        raise FileNotFoundError("sjctl not found")

    monkeypatch.setattr(subprocess, "run", _raise)

    result = await run_solid_jobs_ingestion(db_session, source, campaign="recruflow")
    await db_session.commit()

    assert result == IngestionResult(
        ok=False, fetched=0, created=0, error_message="sjctl call failed"
    )
    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_solid_jobs_ingestion_returns_not_ok_on_malformed_json(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: _FakeCompletedProcess(returncode=0, stdout="not json"),
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
        subprocess,
        "run",
        lambda *a, **kw: _FakeCompletedProcess(
            returncode=0, stdout=_sync_stdout([valid_offer, invalid_offer])
        ),
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
