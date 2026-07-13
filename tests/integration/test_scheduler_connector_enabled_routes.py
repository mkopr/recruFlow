from uuid import uuid4

import httpx
import pytest
from app.db.models import Offer as OfferModel
from app.db.models import SchedulerRun, Source
from app.ingestion import registry
from app.ingestion.normalize import JUSTJOINIT, NOFLUFFJOBS, SOLID_JOBS
from app.ingestion.persist import ingest_offer
from app.ingestion.types import IngestionResult
from app.scheduler.lifecycle import build_job_id
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.integration
@pytest.mark.asyncio
async def test_put_enabled_disables_pauses_live_job_without_restart(
    scheduled_client: httpx.AsyncClient,
) -> None:
    response = await scheduled_client.put(
        "/scheduler/sources/justjoinit/enabled", json={"enabled": False}
    )
    assert response.status_code == 200
    assert response.json()["connector_enabled"] is False

    from app.main import app

    job = app.state.scheduler.get_job(build_job_id(JUSTJOINIT))
    assert job is not None
    assert job.next_run_time is None

    # restore for other tests sharing this persistent db_test instance
    await scheduled_client.put("/scheduler/sources/justjoinit/enabled", json={"enabled": True})


@pytest.mark.integration
@pytest.mark.asyncio
async def test_put_enabled_enable_resumes_a_paused_job(
    scheduled_client: httpx.AsyncClient,
) -> None:
    # This suite runs against the persistent db_test instance -- ensure auto-fetch (the other
    # half of connector_should_auto_run's AND) is on, regardless of what an earlier test/file
    # left behind, so re-enabling connector_enabled alone is sufficient to resume the job.
    await scheduled_client.put("/scheduler/sources/justjoinit/auto-fetch", json={"enabled": True})

    disable_response = await scheduled_client.put(
        "/scheduler/sources/justjoinit/enabled", json={"enabled": False}
    )
    assert disable_response.status_code == 200

    enable_response = await scheduled_client.put(
        "/scheduler/sources/justjoinit/enabled", json={"enabled": True}
    )
    assert enable_response.status_code == 200
    assert enable_response.json()["connector_enabled"] is True

    from app.main import app

    job = app.state.scheduler.get_job(build_job_id(JUSTJOINIT))
    assert job is not None
    assert job.next_run_time is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_put_enabled_unknown_connector_returns_404(
    scheduled_client: httpx.AsyncClient,
) -> None:
    response = await scheduled_client.put(
        "/scheduler/sources/does-not-exist/enabled", json={"enabled": False}
    )
    assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bulk_enabled_toggles_every_connector(scheduled_client: httpx.AsyncClient) -> None:
    from app.main import app

    # See test_put_enabled_enable_resumes_a_paused_job: ensure auto-fetch is on for all three
    # first, since this persistent-DB suite doesn't isolate config_json between tests/files.
    await scheduled_client.put("/scheduler/sources/auto-fetch", json={"enabled": True})

    disable_response = await scheduled_client.put(
        "/scheduler/sources/enabled", json={"enabled": False}
    )
    assert disable_response.status_code == 200
    for connector in (SOLID_JOBS, JUSTJOINIT, NOFLUFFJOBS):
        job = app.state.scheduler.get_job(build_job_id(connector))
        assert job is not None
        assert job.next_run_time is None

    enable_response = await scheduled_client.put(
        "/scheduler/sources/enabled", json={"enabled": True}
    )
    assert enable_response.status_code == 200
    for connector in (SOLID_JOBS, JUSTJOINIT, NOFLUFFJOBS):
        job = app.state.scheduler.get_job(build_job_id(connector))
        assert job is not None
        assert job.next_run_time is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_disabled_source_manual_trigger_returns_409_and_creates_no_scheduler_run(
    scheduled_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> None:
    # Proves the connector is never reached at all: a dispatch that would succeed if called
    # is registered, so a 200 here would mean the guard was bypassed rather than enforced.
    async def _would_succeed(
        session: AsyncSession, source: Source, force_refresh: bool
    ) -> IngestionResult:
        raise AssertionError("disabled connector's dispatch must never be called")

    monkeypatch.setitem(
        registry.CONNECTOR_REGISTRY,
        JUSTJOINIT,
        registry.ConnectorSpec(name=JUSTJOINIT, label="JustJoin.it", dispatch=_would_succeed),
    )

    source = await registry.resolve_source_by_connector(db_session, JUSTJOINIT)
    run_count_before = len(
        (await db_session.execute(select(SchedulerRun).where(SchedulerRun.source_id == source.id)))
        .scalars()
        .all()
    )

    disable_response = await scheduled_client.put(
        "/scheduler/sources/justjoinit/enabled", json={"enabled": False}
    )
    assert disable_response.status_code == 200

    try:
        response = await scheduled_client.post("/scheduler/run/justjoinit")

        assert response.status_code == 409
        assert "justjoinit" in response.json()["detail"]

        run_count_after = len(
            (
                await db_session.execute(
                    select(SchedulerRun).where(SchedulerRun.source_id == source.id)
                )
            )
            .scalars()
            .all()
        )
        assert run_count_after == run_count_before
    finally:
        await scheduled_client.put("/scheduler/sources/justjoinit/enabled", json={"enabled": True})


@pytest.mark.integration
@pytest.mark.asyncio
async def test_connector_enabled_and_auto_fetch_are_independent(
    scheduled_client: httpx.AsyncClient,
) -> None:
    from app.main import app

    job_id = build_job_id(JUSTJOINIT)
    try:
        enabled_response = await scheduled_client.put(
            "/scheduler/sources/justjoinit/enabled", json={"enabled": True}
        )
        assert enabled_response.status_code == 200

        auto_fetch_response = await scheduled_client.put(
            "/scheduler/sources/justjoinit/auto-fetch", json={"enabled": False}
        )
        assert auto_fetch_response.status_code == 200
        assert app.state.scheduler.get_job(job_id).next_run_time is None

        disable_response = await scheduled_client.put(
            "/scheduler/sources/justjoinit/enabled", json={"enabled": False}
        )
        assert disable_response.status_code == 200
        assert app.state.scheduler.get_job(job_id).next_run_time is None

        re_enable_response = await scheduled_client.put(
            "/scheduler/sources/justjoinit/enabled", json={"enabled": True}
        )
        assert re_enable_response.status_code == 200
        # auto_fetch_enabled is still False -- re-enabling the connector alone must not
        # silently resume the scheduled job.
        assert app.state.scheduler.get_job(job_id).next_run_time is None
    finally:
        await scheduled_client.put(
            "/scheduler/sources/justjoinit/auto-fetch", json={"enabled": True}
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_re_enabling_auto_fetch_while_connector_disabled_stays_paused(
    scheduled_client: httpx.AsyncClient,
) -> None:
    from app.main import app

    job_id = build_job_id(JUSTJOINIT)
    try:
        disable_response = await scheduled_client.put(
            "/scheduler/sources/justjoinit/enabled", json={"enabled": False}
        )
        assert disable_response.status_code == 200

        auto_fetch_response = await scheduled_client.put(
            "/scheduler/sources/justjoinit/auto-fetch", json={"enabled": True}
        )
        assert auto_fetch_response.status_code == 200
        # connector_enabled is still False -- turning auto-fetch back on alone must not
        # silently resume the scheduled job (this is the update_source_auto_fetch fix:
        # using connector_should_auto_run instead of blindly trusting payload.enabled).
        assert app.state.scheduler.get_job(job_id).next_run_time is None
    finally:
        await scheduled_client.put("/scheduler/sources/justjoinit/enabled", json={"enabled": True})


@pytest.mark.integration
@pytest.mark.asyncio
async def test_disabled_connector_does_not_touch_existing_offers(
    scheduled_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    # Uses the real, already-registered justjoinit Source (a throwaway connector created after
    # app startup has no live scheduler job yet, which PUT .../enabled's pause/resume would
    # otherwise fail to look up). The offer is checked by direct DB re-fetch afterward rather
    # than via GET /offers?source=, since the real justjoinit Source accumulates offers across
    # this persistent db_test instance's whole history and pagination isn't a reliable way to
    # find one specific offer among them.
    source = await registry.resolve_source_by_connector(db_session, JUSTJOINIT)
    canonical_url = f"https://example.com/jobs/{uuid4()}/disabled-connector-offer"
    ingested = await ingest_offer(
        db_session,
        {
            "source_id": source.id,
            "title": "Backend Engineer",
            "company": "Acme",
            "canonical_url": canonical_url,
        },
        raw_payload={"id": "abc"},
    )
    assert ingested is not None
    offer_id = ingested[0].id
    await db_session.commit()

    try:
        disable_response = await scheduled_client.put(
            "/scheduler/sources/justjoinit/enabled", json={"enabled": False}
        )
        assert disable_response.status_code == 200

        refreshed = await db_session.get(OfferModel, offer_id)
        assert refreshed is not None
        assert refreshed.canonical_url == canonical_url
        assert refreshed.hide is False
        assert refreshed.applied is False
    finally:
        await scheduled_client.put("/scheduler/sources/justjoinit/enabled", json={"enabled": True})
        await db_session.execute(delete(OfferModel).where(OfferModel.id == offer_id))
        await db_session.commit()
