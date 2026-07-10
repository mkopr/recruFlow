from typing import Any

import httpx
import pytest
from app.db.models import Source
from app.db.session import get_engine, get_sessionmaker
from app.ingestion.normalize import JUSTJOINIT, NOFLUFFJOBS, SOLID_JOBS
from sqlalchemy import select


async def _get_source_fetch_range(connector: str) -> dict[str, Any]:
    engine = get_engine()
    sessionmaker = get_sessionmaker(engine)
    async with sessionmaker() as session:
        source = await session.scalar(select(Source).where(Source.connector == connector))
        assert source is not None
        fetch_range: dict[str, Any] = source.config_json.get("fetch_range", {})
        return fetch_range


@pytest.mark.integration
@pytest.mark.asyncio
async def test_put_fetch_range_persists_and_validates(scheduled_client: httpx.AsyncClient) -> None:
    before = await _get_source_fetch_range(JUSTJOINIT)

    reject_response = await scheduled_client.put(
        "/scheduler/sources/justjoinit/fetch-range",
        json={
            "mode": "range",
            "since": "2026-06-30T00:00:00Z",
            "until": "2026-06-01T00:00:00Z",
        },
    )
    assert reject_response.status_code == 422
    assert await _get_source_fetch_range(JUSTJOINIT) == before

    accept_response = await scheduled_client.put(
        "/scheduler/sources/justjoinit/fetch-range",
        json={
            "mode": "range",
            "since": "2026-06-01T00:00:00Z",
            "until": "2026-06-30T00:00:00Z",
        },
    )
    assert accept_response.status_code == 200
    expected = {
        "mode": "range",
        "since": "2026-06-01T00:00:00Z",
        "until": "2026-06-30T00:00:00Z",
    }
    assert accept_response.json()["fetch_range"] == expected
    assert await _get_source_fetch_range(JUSTJOINIT) == expected


@pytest.mark.integration
@pytest.mark.asyncio
async def test_put_fetch_range_accepts_all_mode(scheduled_client: httpx.AsyncClient) -> None:
    response = await scheduled_client.put(
        "/scheduler/sources/nofluffjobs/fetch-range", json={"mode": "all"}
    )
    assert response.status_code == 200
    expected = {"mode": "all", "since": None, "until": None}
    assert response.json()["fetch_range"] == expected
    assert await _get_source_fetch_range(NOFLUFFJOBS) == expected


@pytest.mark.integration
@pytest.mark.asyncio
async def test_put_fetch_range_unknown_connector_returns_404(
    scheduled_client: httpx.AsyncClient,
) -> None:
    response = await scheduled_client.put(
        "/scheduler/sources/does-not-exist/fetch-range", json={"mode": "all"}
    )
    assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bulk_fetch_range_updates_every_connector(
    scheduled_client: httpx.AsyncClient,
) -> None:
    payload = {"mode": "range", "since": "2026-01-01T00:00:00Z", "until": None}
    response = await scheduled_client.put("/scheduler/sources/fetch-range", json=payload)
    assert response.status_code == 200

    entries = {entry["connector"]: entry for entry in response.json()["sources"]}
    for connector in (SOLID_JOBS, JUSTJOINIT, NOFLUFFJOBS):
        assert entries[connector]["fetch_range"] == payload
        assert await _get_source_fetch_range(connector) == payload


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_scheduler_status_reports_fetch_range_and_auto_fetch_enabled(
    scheduled_client: httpx.AsyncClient,
) -> None:
    put_response = await scheduled_client.put(
        "/scheduler/sources/solid_jobs/fetch-range",
        json={"mode": "range", "since": "2026-02-01T00:00:00Z", "until": None},
    )
    assert put_response.status_code == 200

    status_response = await scheduled_client.get("/scheduler/status")
    entries = {entry["connector"]: entry for entry in status_response.json()["sources"]}
    entry = entries[SOLID_JOBS]
    assert entry["fetch_range"] == {
        "mode": "range",
        "since": "2026-02-01T00:00:00Z",
        "until": None,
    }
    assert entry["auto_fetch_enabled"] is True
