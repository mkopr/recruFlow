from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.integration
@pytest.mark.asyncio
async def test_health_returns_200_with_status_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_health_db_returns_200_when_db_reachable(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/db")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_health_db_returns_503_when_db_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.deps import _get_sessionmaker
    from app.main import app

    unreachable_url = "postgresql+asyncpg://recruflow:recruflow@localhost:1/recruflow"
    monkeypatch.setenv("DATABASE_URL", unreachable_url)
    _get_sessionmaker.cache_clear()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/health/db")

    _get_sessionmaker.cache_clear()

    assert response.status_code == 503


@pytest.mark.integration
@pytest.mark.asyncio
async def test_openapi_json_returns_200_and_valid_json(client: httpx.AsyncClient) -> None:
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()
    assert "openapi" in payload


@pytest.mark.integration
@pytest.mark.asyncio
async def test_docs_returns_200(client: httpx.AsyncClient) -> None:
    response = await client.get("/docs")

    assert response.status_code == 200
