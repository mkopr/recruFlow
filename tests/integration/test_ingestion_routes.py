import asyncio
from uuid import uuid4

import httpx
import pytest
from app.connectors import justjoinit, nofluffjobs, solid_jobs
from app.db.models import Offer as OfferModel
from app.db.models import Source
from app.db.session import get_engine, get_sessionmaker
from app.ingestion import registry
from app.ingestion.normalize import JUSTJOINIT
from app.ingestion.persist import ingest_offer
from app.ingestion.types import IngestionResult as JustJoinItIngestionResult
from app.ingestion.types import IngestionResult as NoFluffJobsIngestionResult
from app.ingestion.types import IngestionResult as SolidJobsIngestionResult
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _unique_url(path: str) -> str:
    return f"https://example.com/jobs/{uuid4()}/{path}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_triggers_fetch_and_returns_new_updated_count(
    scheduled_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake(
        session: AsyncSession, source: Source, *, force_refresh: bool = False
    ) -> JustJoinItIngestionResult:
        return JustJoinItIngestionResult(ok=True, fetched=5, created=3)

    monkeypatch.setattr(justjoinit, "run_justjoinit_ingestion", _fake)

    response = await scheduled_client.post("/ingest/justjoinit")

    assert response.status_code == 200
    assert response.json() == {
        "source": "justjoinit",
        "ok": True,
        "fetched": 5,
        "created": 3,
        "error_message": None,
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_persists_offers_end_to_end_visible_in_db(
    scheduled_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    canonical_url = _unique_url("solid-jobs-offer")

    async def _fake(
        session: AsyncSession, source: Source, *, campaign: str, force_refresh: bool = False
    ) -> SolidJobsIngestionResult:
        await ingest_offer(
            session,
            {
                "source_id": source.id,
                "title": "Backend Engineer",
                "company": "Acme",
                "canonical_url": canonical_url,
            },
            raw_payload={"id": "abc"},
        )
        return SolidJobsIngestionResult(ok=True, fetched=1, created=1)

    monkeypatch.setattr(solid_jobs, "run_solid_jobs_ingestion", _fake)

    response = await scheduled_client.post("/ingest/solid_jobs")

    assert response.status_code == 200
    body = response.json()
    assert body["fetched"] == 1
    assert body["created"] == 1

    engine = get_engine()
    sessionmaker = get_sessionmaker(engine)
    async with sessionmaker() as session:
        row = await session.scalar(
            select(OfferModel).where(OfferModel.canonical_url == canonical_url)
        )
    assert row is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_solid_jobs_passes_force_refresh_true(
    scheduled_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, bool] = {}

    async def _fake(
        session: AsyncSession, source: Source, *, campaign: str, force_refresh: bool = False
    ) -> SolidJobsIngestionResult:
        captured["force_refresh"] = force_refresh
        return SolidJobsIngestionResult(ok=True, fetched=0, created=0)

    monkeypatch.setattr(solid_jobs, "run_solid_jobs_ingestion", _fake)

    response = await scheduled_client.post("/ingest/solid_jobs")

    assert response.status_code == 200
    assert captured["force_refresh"] is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_sets_source_last_fetched_at_on_success(
    scheduled_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake(
        session: AsyncSession, source: Source, *, force_refresh: bool = False
    ) -> JustJoinItIngestionResult:
        return JustJoinItIngestionResult(ok=True, fetched=1, created=1)

    monkeypatch.setattr(justjoinit, "run_justjoinit_ingestion", _fake)

    response = await scheduled_client.post("/ingest/justjoinit")
    assert response.status_code == 200

    status_response = await scheduled_client.get("/scheduler/status")
    entries = {entry["connector"]: entry for entry in status_response.json()["sources"]}
    assert entries[JUSTJOINIT]["last_fetched_at"] is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_does_not_set_source_last_fetched_at_on_failure(
    scheduled_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    status_before = await scheduled_client.get("/scheduler/status")
    before = {
        entry["connector"]: entry["last_fetched_at"] for entry in status_before.json()["sources"]
    }

    async def _fake(
        session: AsyncSession, source: Source, *, force_refresh: bool = False
    ) -> JustJoinItIngestionResult:
        raise RuntimeError("boom")

    monkeypatch.setattr(justjoinit, "run_justjoinit_ingestion", _fake)

    response = await scheduled_client.post("/ingest/justjoinit")
    assert response.status_code == 200
    assert response.json()["ok"] is False

    status_after = await scheduled_client.get("/scheduler/status")
    entries = {entry["connector"]: entry for entry in status_after.json()["sources"]}
    assert entries[JUSTJOINIT]["last_fetched_at"] == before[JUSTJOINIT]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_unknown_source_returns_404_with_clear_message(
    scheduled_client: httpx.AsyncClient,
) -> None:
    response = await scheduled_client.post("/ingest/does-not-exist")

    assert response.status_code == 404
    assert "unknown connector" in response.json()["detail"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_known_connector_without_configured_source_returns_404(
    scheduled_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(
        registry.CONNECTOR_REGISTRY, "fake_connector", registry.CONNECTOR_REGISTRY[JUSTJOINIT]
    )

    response = await scheduled_client.post("/ingest/fake_connector")

    assert response.status_code == 404
    assert "no configured source" in response.json()["detail"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_connector_exception_returns_200_ok_false_with_error_message(
    scheduled_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake(
        session: AsyncSession, source: Source, *, force_refresh: bool = False
    ) -> NoFluffJobsIngestionResult:
        raise RuntimeError("boom")

    monkeypatch.setattr(nofluffjobs, "run_nofluffjobs_ingestion", _fake)

    response = await scheduled_client.post("/ingest/nofluffjobs")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["fetched"] == 0
    assert body["created"] == 0
    assert "boom" in body["error_message"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_health_endpoint_responds_during_ingest_run(
    scheduled_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake(
        session: AsyncSession, source: Source, *, force_refresh: bool = False
    ) -> JustJoinItIngestionResult:
        await asyncio.sleep(1.5)
        return JustJoinItIngestionResult(ok=True, fetched=1, created=1)

    monkeypatch.setattr(justjoinit, "run_justjoinit_ingestion", _fake)

    task = asyncio.create_task(scheduled_client.post("/ingest/justjoinit"))
    await asyncio.sleep(0.2)

    loop = asyncio.get_event_loop()
    start = loop.time()
    health_response = await scheduled_client.get("/health")
    elapsed = loop.time() - start

    assert health_response.status_code == 200
    assert elapsed < 1.0

    await task
