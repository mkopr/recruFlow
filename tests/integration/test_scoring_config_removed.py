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
async def test_get_scoring_config_route_is_gone(client: httpx.AsyncClient) -> None:
    response = await client.get("/scoring-config")

    assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_put_scoring_config_route_is_gone(client: httpx.AsyncClient) -> None:
    response = await client.put(
        "/scoring-config",
        json={"grade_a": 0.9, "grade_b": 0.8, "grade_c": 0.7, "grade_d": 0.6},
    )

    assert response.status_code == 404
