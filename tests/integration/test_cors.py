import httpx
import pytest


@pytest.mark.integration
@pytest.mark.asyncio
async def test_offers_endpoint_returns_cors_headers_for_configured_origin(
    scheduled_client: httpx.AsyncClient,
) -> None:
    response = await scheduled_client.get("/offers", headers={"Origin": "http://localhost:5173"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_endpoint_allows_preflight_from_configured_origin(
    scheduled_client: httpx.AsyncClient,
) -> None:
    response = await scheduled_client.options(
        "/ingest/justjoinit",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "POST" in response.headers["access-control-allow-methods"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_offers_endpoint_omits_cors_headers_for_unconfigured_origin(
    scheduled_client: httpx.AsyncClient,
) -> None:
    response = await scheduled_client.get("/offers", headers={"Origin": "http://evil.example"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
