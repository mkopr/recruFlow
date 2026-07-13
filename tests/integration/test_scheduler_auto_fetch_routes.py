import httpx
import pytest
from app.db.models import Source
from app.ingestion import registry
from app.ingestion.normalize import JUSTJOINIT, NOFLUFFJOBS, SOLID_JOBS
from app.ingestion.registry import ConnectorSpec
from app.ingestion.types import IngestionResult
from app.scheduler.lifecycle import build_job_id
from sqlalchemy.ext.asyncio import AsyncSession


def _fake_spec(connector: str, dispatch: registry.Connector) -> ConnectorSpec:
    return ConnectorSpec(
        name=connector, label=registry.CONNECTOR_REGISTRY[connector].label, dispatch=dispatch
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_put_auto_fetch_disables_pauses_live_job_without_restart(
    scheduled_client: httpx.AsyncClient,
) -> None:
    response = await scheduled_client.put(
        "/scheduler/sources/justjoinit/auto-fetch", json={"enabled": False}
    )
    assert response.status_code == 200
    assert response.json()["auto_fetch_enabled"] is False

    from app.main import app

    job = app.state.scheduler.get_job(build_job_id(JUSTJOINIT))
    assert job is not None
    assert job.next_run_time is None

    # This suite runs against the persistent db_test instance (not rolled back between
    # tests/files) -- restore the flag so later tests/files don't inherit a paused job.
    await scheduled_client.put("/scheduler/sources/justjoinit/auto-fetch", json={"enabled": True})


@pytest.mark.integration
@pytest.mark.asyncio
async def test_put_auto_fetch_enable_resumes_a_paused_job(
    scheduled_client: httpx.AsyncClient,
) -> None:
    disable_response = await scheduled_client.put(
        "/scheduler/sources/justjoinit/auto-fetch", json={"enabled": False}
    )
    assert disable_response.status_code == 200

    enable_response = await scheduled_client.put(
        "/scheduler/sources/justjoinit/auto-fetch", json={"enabled": True}
    )
    assert enable_response.status_code == 200
    assert enable_response.json()["auto_fetch_enabled"] is True

    from app.main import app

    job = app.state.scheduler.get_job(build_job_id(JUSTJOINIT))
    assert job is not None
    assert job.next_run_time is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_put_auto_fetch_unknown_connector_returns_404(
    scheduled_client: httpx.AsyncClient,
) -> None:
    response = await scheduled_client.put(
        "/scheduler/sources/does-not-exist/auto-fetch", json={"enabled": False}
    )
    assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bulk_auto_fetch_toggles_every_connector(scheduled_client: httpx.AsyncClient) -> None:
    from app.main import app

    disable_response = await scheduled_client.put(
        "/scheduler/sources/auto-fetch", json={"enabled": False}
    )
    assert disable_response.status_code == 200
    for connector in (SOLID_JOBS, JUSTJOINIT, NOFLUFFJOBS):
        job = app.state.scheduler.get_job(build_job_id(connector))
        assert job is not None
        assert job.next_run_time is None

    enable_response = await scheduled_client.put(
        "/scheduler/sources/auto-fetch", json={"enabled": True}
    )
    assert enable_response.status_code == 200
    for connector in (SOLID_JOBS, JUSTJOINIT, NOFLUFFJOBS):
        job = app.state.scheduler.get_job(build_job_id(connector))
        assert job is not None
        assert job.next_run_time is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_disabled_source_manual_trigger_still_succeeds(
    scheduled_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # auto_fetch_enabled=False only pauses the *automatic* job -- proven deterministically by
    # `job.next_run_time is None` in the tests above (APScheduler's own signal that it will not
    # fire). Sleeping past a real interval to prove "no automatic run occurs" would be slow and
    # non-deterministic, so that pause assertion is the equivalent verification for this test:
    # here we only need to show the *manual* path is unaffected.
    async def _fake(session: AsyncSession, source: Source, force_refresh: bool) -> IngestionResult:
        return IngestionResult(ok=True, fetched=1, created=1)

    monkeypatch.setitem(registry.CONNECTOR_REGISTRY, JUSTJOINIT, _fake_spec(JUSTJOINIT, _fake))

    disable_response = await scheduled_client.put(
        "/scheduler/sources/justjoinit/auto-fetch", json={"enabled": False}
    )
    assert disable_response.status_code == 200

    run_response = await scheduled_client.post("/scheduler/run/justjoinit")
    assert run_response.status_code == 200
    body = run_response.json()
    assert body["status"] == "ok"
    assert body["trigger_type"] == "manual"

    await scheduled_client.put("/scheduler/sources/justjoinit/auto-fetch", json={"enabled": True})
