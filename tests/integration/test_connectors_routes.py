from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from app.db.models import Source
from app.ingestion import registry
from app.ingestion.registry import ConnectorSpec
from app.ingestion.types import IngestionResult
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_connectors_matches_registry(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Monkeypatching a throwaway extra entry into CONNECTOR_REGISTRY and asserting it appears
    # in the response proves the endpoint reads live off the registry rather than a hardcoded
    # frontend-facing list.
    async def _unused_dispatch(
        session: AsyncSession, source: Source, force_refresh: bool
    ) -> IngestionResult:
        raise AssertionError("never dispatched by this test")

    monkeypatch.setitem(
        registry.CONNECTOR_REGISTRY,
        "throwaway",
        ConnectorSpec(name="throwaway", label="Throwaway", dispatch=_unused_dispatch),
    )

    response = await client.get("/connectors")

    assert response.status_code == 200
    body = response.json()
    expected = {(spec.name, spec.label) for spec in registry.CONNECTOR_REGISTRY.values()}
    actual = {(entry["id"], entry["label"]) for entry in body}
    assert actual == expected
    assert ("throwaway", "Throwaway") in actual
