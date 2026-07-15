from typing import Any

import httpx
import pytest
from app.db.models import Source
from app.db.session import get_engine, get_sessionmaker
from app.ingestion.normalize import BULLDOGJOB, JUSTJOINIT, PRACUJ, SOLID_JOBS
from sqlalchemy import select


async def _get_source_fetch_scope(connector: str) -> dict[str, Any]:
    engine = get_engine()
    sessionmaker = get_sessionmaker(engine)
    async with sessionmaker() as session:
        source = await session.scalar(select(Source).where(Source.connector == connector))
        assert source is not None
        fetch_scope: dict[str, Any] = source.config_json.get("fetch_scope", {})
        return fetch_scope


@pytest.mark.integration
@pytest.mark.asyncio
async def test_put_fetch_scope_filtered_persists_for_supported_connector(
    scheduled_client: httpx.AsyncClient,
) -> None:
    response = await scheduled_client.put(
        "/scheduler/sources/solid_jobs/fetch-scope", json={"mode": "filtered"}
    )
    assert response.status_code == 200
    assert response.json()["fetch_scope"] == {"mode": "filtered"}
    assert await _get_source_fetch_scope(SOLID_JOBS) == {"mode": "filtered"}

    status_response = await scheduled_client.get("/scheduler/status")
    entries = {entry["connector"]: entry for entry in status_response.json()["sources"]}
    assert entries[SOLID_JOBS]["fetch_scope"] == {"mode": "filtered"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_put_fetch_scope_all_persists_for_supported_connector(
    scheduled_client: httpx.AsyncClient,
) -> None:
    for connector in (BULLDOGJOB, PRACUJ):
        response = await scheduled_client.put(
            f"/scheduler/sources/{connector}/fetch-scope", json={"mode": "all"}
        )
        assert response.status_code == 200
        assert response.json()["fetch_scope"] == {"mode": "all"}
        assert await _get_source_fetch_scope(connector) == {"mode": "all"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_put_fetch_scope_filtered_rejected_for_unsupported_connector(
    scheduled_client: httpx.AsyncClient,
) -> None:
    before = await _get_source_fetch_scope(JUSTJOINIT)

    response = await scheduled_client.put(
        "/scheduler/sources/justjoinit/fetch-scope", json={"mode": "filtered"}
    )

    assert response.status_code == 400
    assert await _get_source_fetch_scope(JUSTJOINIT) == before


@pytest.mark.integration
@pytest.mark.asyncio
async def test_put_fetch_scope_all_accepted_for_unsupported_connector(
    scheduled_client: httpx.AsyncClient,
) -> None:
    response = await scheduled_client.put(
        "/scheduler/sources/justjoinit/fetch-scope", json={"mode": "all"}
    )

    assert response.status_code == 200
    assert response.json()["fetch_scope"] == {"mode": "all"}
    assert await _get_source_fetch_scope(JUSTJOINIT) == {"mode": "all"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_put_fetch_scope_unknown_connector_returns_404(
    scheduled_client: httpx.AsyncClient,
) -> None:
    response = await scheduled_client.put(
        "/scheduler/sources/does-not-exist/fetch-scope", json={"mode": "all"}
    )
    assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_scheduler_status_reports_fetch_scope_default_when_absent(
    scheduled_client: httpx.AsyncClient,
) -> None:
    # Simulates a pre-existing row that predates this story (no `fetch_scope` key at all,
    # not even the seeded `{"mode": "all"}` default) by writing config_json directly, then
    # confirms the read side fails open -- same convention Fetch Range's own equivalent test
    # precedent established.
    engine = get_engine()
    sessionmaker = get_sessionmaker(engine)
    async with sessionmaker() as session:
        source = await session.scalar(select(Source).where(Source.connector == JUSTJOINIT))
        assert source is not None
        config_without_fetch_scope = {
            key: value for key, value in source.config_json.items() if key != "fetch_scope"
        }
        source.config_json = config_without_fetch_scope
        await session.commit()

    status_response = await scheduled_client.get("/scheduler/status")
    entries = {entry["connector"]: entry for entry in status_response.json()["sources"]}

    assert entries[JUSTJOINIT]["fetch_scope"] == {"mode": "all"}
